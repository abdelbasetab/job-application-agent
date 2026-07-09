"""Email delivery helper for Tracker submissions.

The default path is dry-run, so demos can show autonomous submission without
accidentally sending real applications. Set EMAIL_DRY_RUN=false plus SMTP
credentials to send for real.
"""

from __future__ import annotations

import base64
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from job_agent.schemas import GeneratedApplication, JobPosting
from job_agent.tools.email_account import EmailAccount, account_from_settings
from job_agent.utils.config import settings


def send_follow_up_email(
    job: JobPosting,
    body_md: str,
    recipient: str | None = None,
    account: EmailAccount | None = None,
) -> dict[str, Any]:
    """Send or dry-run a polite follow-up email for a submitted application.

    Same safety model as :func:`send_application_email`: dry-run by default,
    real SMTP only with EMAIL_DRY_RUN=false plus credentials.
    """
    resolved = account or account_from_settings()
    resolved_recipient = (recipient or settings.email_demo_recipient or "").strip()
    if not resolved_recipient:
        raise ValueError(
            "No email recipient configured. Set EMAIL_DEMO_RECIPIENT or enter one in the UI."
        )
    sender = resolved.sender
    if not sender:
        sender = "job-agent@example.local"

    subject = f"Nachfrage zu meiner Bewerbung: {job.title} - {job.company}"
    body = f"{body_md}\n\n---\nQuelle der Stelle:\n{job.url}\n"
    message = _build_message(sender, resolved_recipient, subject, body, [])

    if settings.email_dry_run:
        return {
            "sent": False,
            "dry_run": True,
            "recipient": resolved_recipient,
            "subject": subject,
            "attachments": [],
            "body_preview": body[:900],
        }
    if not resolved.smtp_host:
        raise ValueError("EMAIL_SMTP_HOST is required when EMAIL_DRY_RUN=false.")
    with smtplib.SMTP(resolved.smtp_host, resolved.smtp_port, timeout=30) as smtp:
        if resolved.use_tls:
            smtp.starttls()
        login_user = resolved.smtp_user or resolved.email_address
        if resolved.auth_method == "oauth":
            _smtp_xoauth2(smtp, login_user, resolved.access_token)
        elif login_user:
            smtp.login(login_user, resolved.smtp_password)
        smtp.send_message(message)
    return {
        "sent": True,
        "dry_run": False,
        "recipient": resolved_recipient,
        "subject": subject,
        "attachments": [],
    }


def send_application_email(
    job: JobPosting,
    application: GeneratedApplication,
    recipient: str | None = None,
    attachments: list[Path] | None = None,
    account: EmailAccount | None = None,
) -> dict[str, Any]:
    """Send or dry-run a generated application email, optionally with attachments."""
    resolved = account or account_from_settings()
    resolved_recipient = (recipient or settings.email_demo_recipient or "").strip()
    if not resolved_recipient:
        raise ValueError("No email recipient configured. Set EMAIL_DEMO_RECIPIENT or enter one in the UI.")

    sender = resolved.sender
    if not sender:
        sender = "job-agent@example.local"

    files = [Path(p) for p in (attachments or []) if Path(p).is_file()]
    subject = f"Bewerbung: {job.title} - {job.company}"
    body = _email_body(job, application)
    message = _build_message(sender, resolved_recipient, subject, body, files)
    attachment_names = [f.name for f in files]

    if settings.email_dry_run:
        return {
            "sent": False,
            "dry_run": True,
            "recipient": resolved_recipient,
            "subject": subject,
            "attachments": attachment_names,
            "body_preview": body[:900],
        }

    if not resolved.smtp_host:
        raise ValueError("EMAIL_SMTP_HOST is required when EMAIL_DRY_RUN=false.")

    with smtplib.SMTP(resolved.smtp_host, resolved.smtp_port, timeout=30) as smtp:
        if resolved.use_tls:
            smtp.starttls()
        login_user = resolved.smtp_user or resolved.email_address
        if resolved.auth_method == "oauth":
            _smtp_xoauth2(smtp, login_user, resolved.access_token)
        elif login_user:
            smtp.login(login_user, resolved.smtp_password)
        smtp.send_message(message)

    return {
        "sent": True,
        "dry_run": False,
        "recipient": resolved_recipient,
        "subject": subject,
        "attachments": attachment_names,
    }


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


def _email_body(job: JobPosting, application: GeneratedApplication) -> str:
    return (
        f"{application.cover_letter_md}\n\n"
        "---\n"
        "Quelle der Stelle:\n"
        f"{job.url}\n\n"
        "Diese E-Mail wurde vom Job Application Agent vorbereitet."
    )
