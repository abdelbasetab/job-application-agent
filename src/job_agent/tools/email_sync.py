"""Email inbox sync for Tracker status updates.

The sync path is conservative by design: EMAIL_SYNC_DRY_RUN=true returns
proposed updates without changing the database. Disable it only after testing
with a dedicated mailbox or label/folder.
"""

from __future__ import annotations

import email
import imaplib
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header
from email.message import Message
from typing import Any, Literal

from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, JobPosting
from job_agent.tools.email_account import EmailAccount, account_from_settings
from job_agent.utils.config import settings

DetectedStage = Literal["submitted", "interview", "rejected", "offer", "unknown"]

_REJECTION_TERMS = [
    "leider",
    "absage",
    "nicht berücksichtigen",
    "nicht beruecksichtigen",
    "anderen bewerber",
    "anderweitig entschieden",
    "we regret",
    "unfortunately",
    "not move forward",
]
_INTERVIEW_TERMS = [
    "vorstellungsgespräch",
    "vorstellungsgespraech",
    "interview",
    "kennenlernen",
    "gespräch einladen",
    "gespraech einladen",
    "termin",
    "video call",
]
_OFFER_TERMS = [
    "angebot",
    "offer",
    "vertrag",
    "einstellungsangebot",
    "wir freuen uns, ihnen ein angebot",
]
_CONFIRMATION_TERMS = [
    "vielen dank für ihre bewerbung",
    "vielen dank fuer ihre bewerbung",
    "bewerbung erhalten",
    "eingang ihrer bewerbung",
    "thank you for your application",
    "received your application",
]


@dataclass(frozen=True)
class InboxMessage:
    uid: str
    subject: str
    sender: str
    body: str
    received_at: datetime | None = None


def sync_email_statuses(
    store: Store,
    limit: int | None = None,
    account: EmailAccount | None = None,
) -> dict[str, Any]:
    """Fetch recent inbox messages and update or propose tracker statuses."""
    messages = fetch_inbox_messages(limit or settings.email_sync_limit, account=account)
    return sync_messages(store, messages, dry_run=settings.email_sync_dry_run)


def sync_messages(
    store: Store,
    messages: list[InboxMessage],
    dry_run: bool = True,
) -> dict[str, Any]:
    jobs = store.all_jobs()
    statuses = {status.job_id: status for status in store.all_status()}
    updates: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    ignored = 0
    classified = 0
    matched = 0

    for message in messages:
        stage = classify_message(message.subject, message.body)
        if stage == "unknown":
            ignored += 1
            continue
        classified += 1
        job = match_message_to_job(message, jobs)
        match_method = "job_text"
        if job is None:
            job = match_message_to_tracked_application(message, jobs, statuses, store)
            match_method = "tracked_application" if job else ""
        if job is None:
            if len(unmatched) < 8:
                unmatched.append(
                    _message_diagnostic(
                        message,
                        stage,
                        "Keine Bewerbung mit passender Firma, Stelle oder eindeutiger aktiver Bewerbung gefunden.",
                    )
                )
            continue
        matched += 1
        existing = statuses.get(job.id)
        note = _event_note(message, stage)
        update = {
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "stage": stage,
            "subject": message.subject,
            "sender": message.sender,
            "match_method": match_method,
            "dry_run": dry_run,
        }
        updates.append(update)
        if dry_run:
            continue

        submitted_at = existing.submitted_at if existing else None
        if stage == "submitted" and submitted_at is None:
            submitted_at = message.received_at or datetime.now()
        status = ApplicationStatus(
            job_id=job.id,
            status=stage,
            submitted_at=submitted_at,
            updated_at=datetime.now(),
            notes=_append_note(existing.notes if existing else "", note),
        )
        store.upsert_status(status)
        statuses[job.id] = status

    return {
        "ok": True,
        "dry_run": dry_run,
        "seen": len(messages),
        "ignored": ignored,
        "classified": classified,
        "matched": matched,
        "unmatched": unmatched,
        "updates": updates,
    }


def fetch_inbox_messages(
    limit: int = 50,
    account: EmailAccount | None = None,
) -> list[InboxMessage]:
    resolved = account or account_from_settings()
    if not resolved.imap_host:
        raise ValueError("EMAIL_IMAP_HOST is required for inbox sync.")
    if not resolved.imap_user:
        raise ValueError("EMAIL_IMAP_USER is required for inbox sync.")
    if resolved.auth_method != "oauth" and not resolved.imap_password:
        raise ValueError("EMAIL_IMAP_PASSWORD is required for inbox sync.")
    if resolved.auth_method == "oauth" and not resolved.access_token:
        raise ValueError("OAuth access token is required for inbox sync.")

    messages: list[InboxMessage] = []
    with imaplib.IMAP4_SSL(resolved.imap_host, resolved.imap_port) as imap:
        if resolved.auth_method == "oauth":
            imap.authenticate(
                "XOAUTH2",
                lambda _: _imap_xoauth2(resolved.imap_user, resolved.access_token),
            )
        else:
            imap.login(resolved.imap_user, resolved.imap_password)
        imap.select(resolved.imap_folder)
        status, raw_ids = imap.search(None, "ALL")
        if status != "OK" or not raw_ids:
            return []
        ids = raw_ids[0].split()[-limit:]
        for raw_id in reversed(ids):
            status, data = imap.fetch(raw_id, "(RFC822)")
            if status != "OK" or not data:
                continue
            for item in data:
                if not isinstance(item, tuple):
                    continue
                parsed = email.message_from_bytes(item[1])
                messages.append(_message_from_email(raw_id.decode("ascii", "ignore"), parsed))
    return messages


def classify_message(subject: str, body: str) -> DetectedStage:
    text = f"{subject}\n{body}".lower()
    if _contains_any(text, _OFFER_TERMS):
        return "offer"
    if _contains_any(text, _INTERVIEW_TERMS):
        return "interview"
    if _contains_any(text, _REJECTION_TERMS):
        return "rejected"
    if _contains_any(text, _CONFIRMATION_TERMS):
        return "submitted"
    return "unknown"


def match_message_to_job(message: InboxMessage, jobs: list[JobPosting]) -> JobPosting | None:
    text = _message_text(message)
    ranked: list[tuple[int, JobPosting]] = []
    for job in jobs:
        score = _job_text_score(text, job)
        if score:
            ranked.append((score, job))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def match_message_to_tracked_application(
    message: InboxMessage,
    jobs: list[JobPosting],
    statuses: dict[str, ApplicationStatus],
    store: Store,
) -> JobPosting | None:
    """Conservative fallback for replies that omit the exact job title.

    Many recruiter replies only mention the company and a generic invitation.
    If a message is already classified as a real application event, match it
    against applications that the tracker knows about instead of every scraped
    job. If only one active application exists, we accept it as a demo-friendly
    fallback; otherwise at least a weak company/title signal is required.
    """
    text = _message_text(message)
    candidates: list[tuple[int, datetime, JobPosting]] = []
    active_jobs: list[tuple[datetime, JobPosting]] = []
    for job in jobs:
        status = statuses.get(job.id)
        application = store.get_application(job.id)
        if status is None and application is None:
            continue
        if status and status.status in {"rejected", "offer", "withdrawn"}:
            continue
        last_activity = status.updated_at if status else datetime.min
        active_jobs.append((last_activity, job))
        score = _job_text_score(text, job)
        if status and status.status == "submitted":
            score += 1
        if score >= 2:
            candidates.append((score, last_activity, job))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]
    if len(active_jobs) == 1:
        return active_jobs[0][1]
    return None


def _message_from_email(uid: str, message: Message) -> InboxMessage:
    return InboxMessage(
        uid=uid,
        subject=_decode_header_value(message.get("Subject", "")),
        sender=_decode_header_value(message.get("From", "")),
        body=_plain_body(message),
        received_at=None,
    )


def _plain_body(message: Message) -> str:
    if message.is_multipart():
        parts: list[str] = []
        for part in message.walk():
            if part.get_content_type() != "text/plain":
                continue
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            charset = part.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="replace"))
        return "\n".join(parts)
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(message.get_payload() or "")


def _decode_header_value(value: str) -> str:
    chunks: list[str] = []
    for raw, charset in decode_header(value):
        if isinstance(raw, bytes):
            chunks.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            chunks.append(raw)
    return "".join(chunks)


def _imap_xoauth2(user: str, access_token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {access_token}\x01\x01".encode()


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _message_text(message: InboxMessage) -> str:
    return _normalize_text(f"{message.subject}\n{message.sender}\n{message.body}")


def _job_text_score(text: str, job: JobPosting) -> int:
    score = 0
    company = _normalize_text(job.company)
    title = _normalize_text(job.title)
    domain_hint = _domain_hint(job.company)
    if company and company in text:
        score += 4
    if title and title in text:
        score += 3
    if domain_hint and domain_hint in text:
        score += 2
    if str(job.url).lower() in text:
        score += 5
    token_hits = sum(1 for token in _company_tokens(job.company) if token in text)
    if token_hits:
        score += min(3, token_hits)
    return score


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").replace("_", " ").split())


def _company_tokens(company: str) -> list[str]:
    legal_suffixes = {
        "ag",
        "co",
        "company",
        "gbr",
        "gmbh",
        "group",
        "gruppe",
        "inc",
        "kg",
        "ltd",
        "ohg",
        "se",
    }
    return [
        token
        for token in _normalize_text(company).split()
        if len(token) >= 3 and token not in legal_suffixes
    ]


def _domain_hint(company: str) -> str:
    return "".join(ch for ch in company.lower().split()[0] if ch.isalnum()) if company.split() else ""


def _event_note(message: InboxMessage, stage: DetectedStage) -> str:
    return f"Inbox: {stage} erkannt von {message.sender}: {message.subject}"


def _message_diagnostic(
    message: InboxMessage,
    stage: DetectedStage,
    reason: str,
) -> dict[str, Any]:
    return {
        "uid": message.uid,
        "stage": stage,
        "subject": message.subject[:160],
        "sender": message.sender[:160],
        "reason": reason,
    }


def _append_note(existing: str, event: str) -> str:
    merged = f"{existing}\n{event}".strip() if existing else event
    return merged[-1000:]
