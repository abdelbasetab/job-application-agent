"""Conservative, de-duplicated IMAP-to-tracker synchronization."""

from __future__ import annotations

import email
import hashlib
import imaplib
import re
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Literal

from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, JobPosting
from job_agent.tools.email_account import EmailAccount, account_from_settings
from job_agent.utils.config import settings
from job_agent.utils.network_security import validate_public_host

DetectedStage = Literal["submitted", "interview", "rejected", "offer", "unknown"]

_REJECTION_PATTERNS = [
    r"\babsage\b",
    r"\bnicht\s+(?:weiter\s+)?beruecksichtigen\b",
    r"\bnicht\s+(?:weiter\s+)?berücksichtigen\b",
    r"\bandere[nr]?\s+bewerber",
    r"\banderweitig\s+entschieden\b",
    r"\bwe\s+regret\b",
    r"\bnot\s+move\s+forward\b",
    r"\bwon't\s+move\s+forward\b",
    r"\bwill\s+not\s+be\s+moving\s+forward\b",
    r"\b(?:kein|keine|keinen|keinem|keiner)\s+(?:angebot|vertrag)",
    r"\b(?:cannot|can't|unable\s+to)\s+(?:make\s+you\s+an?\s+)?offer\b",
]
_INTERVIEW_PATTERNS = [
    r"\bvorstellungsgespr(?:ae|ä)ch\b",
    r"\binterview(?:termin|gespr(?:ae|ä)ch)?\b",
    r"\bzu\s+einem\s+(?:persoenlichen\s+|persönlichen\s+)?gespr(?:ae|ä)ch\s+einladen\b",
    r"\bkennenlernen\s+(?:einladen|vereinbaren)\b",
    r"\bvideo\s*call\b",
]
_OFFER_PATTERNS = [
    r"\bwir\s+freuen\s+uns[^.\n]{0,80}\bangebot\b",
    r"\b(?:stellen|job)angebot\b",
    r"\beinstellungsangebot\b",
    r"\bvertrag\s+(?:anbei|zusenden|vorbereitet|unterschreiben)\b",
    r"\b(?:pleased|happy|delighted)\s+to\s+(?:make|extend|offer)\b",
    r"\bformal\s+offer\b",
    r"\bjob\s+offer\b",
]
_CONFIRMATION_PATTERNS = [
    r"\bvielen\s+dank\s+f(?:ue|ü)r\s+ihre\s+bewerbung\b",
    r"\bbewerbung\s+(?:ist\s+)?(?:bei\s+uns\s+)?eingegangen\b",
    r"\beingang\s+ihrer\s+bewerbung\b",
    r"\bthank\s+you\s+for\s+your\s+application\b",
    r"\breceived\s+your\s+application\b",
]

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted", "interview", "rejected", "offer"},
    "submitted": {"interview", "rejected", "offer"},
    "interview": {"rejected", "offer"},
    "rejected": set(),
    "offer": set(),
    "withdrawn": set(),
}


@dataclass(frozen=True)
class InboxMessage:
    uid: str
    subject: str
    sender: str
    body: str
    received_at: datetime | None = None
    message_id: str = ""

    @property
    def key(self) -> str:
        canonical_id = self.message_id.strip().casefold()
        if canonical_id:
            return "message-id:" + canonical_id
        raw = "\0".join(
            [
                self.uid,
                self.sender.casefold(),
                self.subject.casefold(),
                self.received_at.isoformat() if self.received_at else "",
                self.body,
            ]
        )
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sync_email_statuses(
    store: Store,
    limit: int | None = None,
    account: EmailAccount | None = None,
) -> dict[str, Any]:
    resolved = account or account_from_settings()
    messages = fetch_inbox_messages(limit or settings.email_sync_limit, account=resolved)
    return sync_messages(store, messages, dry_run=resolved.sync_dry_run)


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
    duplicates = 0
    blocked_transitions = 0

    # IMAP often returns newest first. Applying oldest first prevents an old
    # receipt confirmation from downgrading a later interview invitation.
    ordered = sorted(messages, key=_chronological_key)
    for message in ordered:
        if not dry_run and store.email_processed(message.key):
            duplicates += 1
            continue
        stage = classify_message(message.subject, message.body)
        if stage == "unknown":
            ignored += 1
            if not dry_run:
                _record_without_status(store, message, stage, "unknown")
            continue
        classified += 1
        job = match_message_to_job(message, jobs)
        match_method = "job_text"
        if job is None:
            job = match_message_to_tracked_application(message, jobs, statuses, store)
            match_method = "tracked_application" if job else ""
        if job is None:
            if not dry_run:
                _record_without_status(store, message, stage, "unmatched")
            if len(unmatched) < 8:
                unmatched.append(
                    _message_diagnostic(
                        message,
                        stage,
                        "Keine eindeutig passende Bewerbung anhand Firma/Stelle gefunden.",
                    )
                )
            continue
        matched += 1
        existing = statuses.get(job.id)
        allowed = _transition_allowed(existing.status if existing else None, stage)
        update = {
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "stage": stage,
            "subject": message.subject,
            "sender": message.sender,
            "received_at": message.received_at.isoformat() if message.received_at else None,
            "match_method": match_method,
            "dry_run": dry_run,
            "transition_allowed": allowed,
        }
        updates.append(update)
        if dry_run:
            continue
        if not allowed:
            blocked_transitions += 1
            _record_without_status(store, message, stage, "blocked_transition", job.id)
            continue

        submitted_at = existing.submitted_at if existing else None
        if stage == "submitted" and submitted_at is None:
            submitted_at = message.received_at or datetime.now()
        status = ApplicationStatus(
            job_id=job.id,
            status=stage,
            submitted_at=submitted_at,
            updated_at=message.received_at or datetime.now(),
            notes=_append_note(existing.notes if existing else "", _event_note(message, stage)),
        )
        applied = store.apply_inbox_status(
            message.key,
            status,
            uid=message.uid,
            message_id=message.message_id or None,
            received_at=message.received_at,
            stage=stage,
            payload={"subject": message.subject[:240], "sender": message.sender[:240]},
        )
        if not applied:
            duplicates += 1
            continue
        statuses[job.id] = status

    return {
        "ok": True,
        "dry_run": dry_run,
        "seen": len(messages),
        "ignored": ignored,
        "classified": classified,
        "matched": matched,
        "duplicates": duplicates,
        "blocked_transitions": blocked_transitions,
        "unmatched": unmatched,
        "updates": updates,
    }


def fetch_inbox_messages(
    limit: int = 50,
    account: EmailAccount | None = None,
) -> list[InboxMessage]:
    resolved = account or account_from_settings()
    if not resolved.imap_ready:
        raise ValueError("IMAP ist fuer dieses Konto nicht vollstaendig konfiguriert.")
    if not re.fullmatch(r"[\w .\-/]{1,120}", resolved.imap_folder, flags=re.UNICODE):
        raise ValueError("Ungueltiger IMAP-Ordner.")
    validate_public_host(
        resolved.imap_host,
        resolved.imap_port,
        allow_private=settings.allow_private_network_services,
    )

    messages: list[InboxMessage] = []
    capped_limit = max(1, min(500, int(limit)))
    with imaplib.IMAP4_SSL(
        resolved.imap_host,
        resolved.imap_port,
        ssl_context=ssl.create_default_context(),
        timeout=30,
    ) as imap:
        if resolved.auth_method == "oauth":
            imap.authenticate(
                "XOAUTH2",
                lambda _: _imap_xoauth2(resolved.imap_user, resolved.access_token),
            )
        else:
            imap.login(resolved.imap_user, resolved.imap_password)
        selected, _ = imap.select(resolved.imap_folder, readonly=True)
        if selected != "OK":
            raise ValueError("IMAP-Ordner konnte nicht schreibgeschuetzt geoeffnet werden.")
        status, raw_ids = imap.uid("search", None, "ALL")  # type: ignore[arg-type]
        if status != "OK" or not raw_ids:
            return []
        ids = raw_ids[0].split()[-capped_limit:]
        for raw_id in ids:
            status, data = imap.uid("fetch", raw_id, "(BODY.PEEK[])")
            if status != "OK" or not data:
                continue
            for item in data:
                if not isinstance(item, tuple) or not isinstance(item[1], bytes):
                    continue
                parsed = email.message_from_bytes(item[1])
                messages.append(_message_from_email(raw_id.decode("ascii", "ignore"), parsed))
    return sorted(messages, key=_chronological_key)


def classify_message(subject: str, body: str) -> DetectedStage:
    text = _normalize_text(f"{subject}\n{body}")
    # Rejection comes first so "we cannot offer" can never be an offer.
    if _matches_any(text, _REJECTION_PATTERNS):
        return "rejected"
    if _matches_any(text, _OFFER_PATTERNS):
        return "offer"
    if _matches_any(text, _INTERVIEW_PATTERNS):
        return "interview"
    if _matches_any(text, _CONFIRMATION_PATTERNS):
        return "submitted"
    return "unknown"


def match_message_to_job(message: InboxMessage, jobs: list[JobPosting]) -> JobPosting | None:
    return _unique_job_match(message, jobs, minimum=3)


def match_message_to_tracked_application(
    message: InboxMessage,
    jobs: list[JobPosting],
    statuses: dict[str, ApplicationStatus],
    store: Store,
) -> JobPosting | None:
    """Match only tracked, non-terminal applications; never guess from one row."""
    tracked = [
        job
        for job in jobs
        if (statuses.get(job.id) is not None or store.get_application(job.id) is not None)
        and (statuses.get(job.id) is None or statuses[job.id].status not in {"withdrawn"})
    ]
    return _unique_job_match(message, tracked, minimum=3)


def _unique_job_match(
    message: InboxMessage, jobs: list[JobPosting], *, minimum: int
) -> JobPosting | None:
    text = _message_text(message)
    ranked = sorted(
        ((_job_text_score(text, job), job) for job in jobs),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < minimum:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 2:
        return None
    return ranked[0][1]


def _message_from_email(uid: str, message: Message) -> InboxMessage:
    received_at: datetime | None = None
    raw_date = str(message.get("Date", ""))
    if raw_date:
        try:
            received_at = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError, OverflowError):
            received_at = None
    return InboxMessage(
        uid=uid,
        subject=_decode_header_value(str(message.get("Subject", ""))),
        sender=_decode_header_value(str(message.get("From", ""))),
        body=_message_body(message),
        received_at=received_at,
        message_id=str(message.get("Message-ID", "")).strip(),
    )


def _message_body(message: Message) -> str:
    plain: list[str] = []
    html_parts: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            value = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        else:
            value = str(part.get_payload() or "")
        if content_type == "text/plain":
            plain.append(value)
        else:
            html_parts.append(value)
    if plain:
        return "\n".join(plain)
    return "\n".join(_html_to_text(value) for value in html_parts)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif tag in {"br", "p", "div", "li", "tr"} and not self._ignored_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in {"p", "div", "li", "tr"} and not self._ignored_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


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


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _message_text(message: InboxMessage) -> str:
    return _normalize_text(f"{message.subject}\n{message.sender}\n{message.body}")


def _job_text_score(text: str, job: JobPosting) -> int:
    score = 0
    company = _normalize_text(job.company)
    title = _normalize_text(job.title)
    domain_hint = _domain_hint(job.company)
    if company and _contains_phrase(text, company):
        score += 4
    if title and _contains_phrase(text, title):
        score += 3
    if domain_hint and _contains_phrase(text, domain_hint):
        score += 2
    if str(job.url).casefold() in text:
        score += 5
    token_hits = sum(
        1 for token in _company_tokens(job.company) if _contains_phrase(text, token)
    )
    return score + min(3, token_hits)


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


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
    return "".join(ch for ch in company.casefold().split()[0] if ch.isalnum()) if company.split() else ""


def _transition_allowed(current: str | None, incoming: DetectedStage) -> bool:
    if incoming == "unknown":
        return False
    if current is None:
        return True
    if current == incoming:
        return False
    return incoming in _ALLOWED_TRANSITIONS.get(current, set())


def _chronological_key(message: InboxMessage) -> tuple[float, int, str]:
    timestamp = 0.0
    if message.received_at is not None:
        try:
            timestamp = message.received_at.timestamp()
        except (OSError, OverflowError, ValueError):
            timestamp = 0.0
    uid_number = int(message.uid) if message.uid.isdigit() else 0
    return timestamp, uid_number, message.uid


def _record_without_status(
    store: Store,
    message: InboxMessage,
    stage: DetectedStage,
    outcome: str,
    job_id: str | None = None,
) -> None:
    store.record_processed_email(
        message.key,
        uid=message.uid,
        message_id=message.message_id or None,
        received_at=message.received_at,
        job_id=job_id,
        stage=None if stage == "unknown" else stage,
        payload={
            "outcome": outcome,
            "subject": message.subject[:240],
            "sender": message.sender[:240],
        },
    )


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
