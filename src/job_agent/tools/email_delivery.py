"""Safe SMTP delivery for applications and follow-ups.

The app never emails an employer directly. Every message this module sends —
application or follow-up — goes to the operator's own configured
``review_email`` address, so a human checks the content and attachments and
forwards them manually. Dry-run is an account policy, not a process-global
policy for web users. The caller reserves an idempotency key in
:mod:`job_agent.memory.store` before entering this module; this module is
intentionally limited to constructing and delivering exactly one message.
"""

from __future__ import annotations

import base64
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any

from job_agent.schemas import GeneratedApplication, JobPosting
from job_agent.tools.email_account import (
    EmailAccount,
    account_from_settings,
    normalize_email_address,
)
from job_agent.tools.recipient_extraction import best_recipient
from job_agent.utils.config import settings
from job_agent.utils.network_security import validate_public_host


def send_follow_up_email(
    job: JobPosting,
    body_md: str,
    account: EmailAccount | None = None,
) -> dict[str, Any]:
    resolved = account or account_from_settings()
    target = _review_target(resolved)
    sender = _sender(resolved)
    subject = _safe_subject(f"Kontrolle: Nachfrage zu {job.title} - {job.company}")
    body = _review_note(job) + "\n\n" + _markdown_to_plain(body_md)
    message = _build_message(sender, target, subject, body, [])
    return _deliver(message, resolved, target, subject, body, [])


def send_application_email(
    job: JobPosting,
    application: GeneratedApplication,
    attachments: list[Path] | None = None,
    account: EmailAccount | None = None,
) -> dict[str, Any]:
    resolved = account or account_from_settings()
    target = _review_target(resolved)
    sender = _sender(resolved)
    files = [Path(path) for path in (attachments or []) if Path(path).is_file()]
    subject = _safe_subject(f"Kontrolle: Bewerbung {job.title} - {job.company}")
    body = _email_body(job, application)
    message = _build_message(sender, target, subject, body, files)
    return _deliver(message, resolved, target, subject, body, files)


def _deliver(
    message: EmailMessage,
    account: EmailAccount,
    recipient: str,
    subject: str,
    body: str,
    attachments: list[Path],
) -> dict[str, Any]:
    names = [path.name for path in attachments]
    message_id = str(message["Message-ID"] or "")
    if account.dry_run:
        return {
            "sent": False,
            "dry_run": True,
            "recipient": recipient,
            "subject": subject,
            "attachments": names,
            "body_preview": body[:900],
            "message_id": message_id,
        }
    if not account.smtp_ready:
        raise ValueError("SMTP ist fuer dieses Konto nicht vollstaendig konfiguriert.")
    if not account.use_tls:
        raise ValueError("SMTP-Versand ohne TLS ist aus Sicherheitsgruenden nicht erlaubt.")
    validate_public_host(
        account.smtp_host,
        account.smtp_port,
        allow_private=settings.allow_private_network_services,
    )
    tls_context = ssl.create_default_context()
    connection: smtplib.SMTP
    if account.smtp_port == 465:
        connection = smtplib.SMTP_SSL(
            account.smtp_host,
            account.smtp_port,
            timeout=30,
            context=tls_context,
        )
    else:
        connection = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=30)
    with connection as smtp:
        if account.smtp_port != 465:
            smtp.starttls(context=tls_context)
        login_user = account.smtp_user or account.email_address
        if account.auth_method == "oauth":
            _smtp_xoauth2(smtp, login_user, account.access_token)
        else:
            smtp.login(login_user, account.smtp_password)
        smtp.send_message(message)
    return {
        "sent": True,
        "dry_run": False,
        "recipient": recipient,
        "subject": subject,
        "attachments": names,
        "message_id": message_id,
    }


def _review_target(account: EmailAccount) -> str:
    """The one address this module is allowed to send to: the operator's own."""
    candidate = account.review_email or (
        settings.email_demo_recipient if account.dry_run else ""
    ) or ""
    cleaned = normalize_email_address(candidate)
    if not cleaned:
        raise ValueError(
            "Keine Kontroll-E-Mail-Adresse hinterlegt. Bitte zuerst in den "
            "Einstellungen eine eigene Adresse eintragen, an die "
            "Bewerbungs-Kontrollpakete gehen sollen."
        )
    return cleaned


def _sender(account: EmailAccount) -> str:
    cleaned = normalize_email_address(account.sender)
    if cleaned:
        return cleaned
    if account.dry_run:
        return "job-agent@example.invalid"
    raise ValueError("Fuer echten Versand ist eine gueltige Absenderadresse erforderlich.")


def _safe_subject(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:240]


def _build_message(
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid()
    message.set_content(body)
    for path in attachments or []:
        message.add_attachment(
            path.read_bytes(),
            maintype="application",
            subtype="pdf" if path.suffix.lower() == ".pdf" else "octet-stream",
            filename=path.name,
        )
    return message


def _smtp_xoauth2(smtp: smtplib.SMTP, user: str, access_token: str) -> None:
    if not user or not access_token:
        raise ValueError("OAuth SMTP requires user and access token.")
    auth = base64.b64encode(
        f"user={user}\x01auth=Bearer {access_token}\x01\x01".encode()
    ).decode("ascii")
    code, response = smtp.docmd("AUTH", "XOAUTH2 " + auth)
    if code >= 400:
        raise smtplib.SMTPAuthenticationError(code, response)


def _markdown_to_plain(value: str) -> str:
    """Convert the small Markdown subset produced by the Writer to plain text."""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^\s*\*\*Betreff:.*?\*\*\s*\n+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "- ", text)
    text = re.sub(r"(?m)^\s*---+\s*$", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?<!\*)\*(?!\*)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _email_body(job: JobPosting, application: GeneratedApplication) -> str:
    return _review_note(job) + "\n\n---\n\n" + _markdown_to_plain(application.cover_letter_md)


def _review_note(job: JobPosting) -> str:
    """Job context for the operator's own inbox — never sent to an employer."""
    detected = best_recipient(job)
    lines = [
        "Dies ist ein Kontrollpaket fuer dich selbst, keine Bewerbung an den Arbeitgeber.",
        "Bitte pruefen und bei Bedarf selbst an den Arbeitgeber weiterleiten.",
        "",
        f"Stelle: {job.title}",
        f"Unternehmen: {job.company}",
        f"Anzeige: {job.url}",
    ]
    if detected:
        lines.append(f"Im Inserat erkannte Bewerbungsadresse: {detected}")
    return "\n".join(lines)
