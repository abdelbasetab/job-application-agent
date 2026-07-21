"""URL-Inbox — das „Second Brain" für gefundene Stellen.

Links (oder komplette Stellenanzeigen als Text) landen jederzeit in einer
leichtgewichtigen Inbox und werden später gesammelt bewertet. Zwei Wege:

1. **Merken:** nur die URL + Notiz ablegen (``add_item``), Status pflegen
   (neu → bewertet / verworfen).
2. **Sofort bewerten:** eingefügten Anzeigentext in ein valides
   :class:`JobPosting` überführen (``posting_from_text``) und durch
   Matcher → Writer → Tracker schicken (``evaluate_pasted_job``) — derselbe
   Weg wie in der Pipeline, nur für genau eine Stelle.

Die Inbox ist bewusst eine JSON-Datei im Nutzer-Datenverzeichnis
(User-Layer, siehe DATA_CONTRACT.md): menschenlesbar, trivial zu sichern,
kein Schema-Eingriff in den SQLite-Store.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from job_agent.agents.matcher import run_matcher
from job_agent.agents.tracker import run_tracker
from job_agent.agents.writer import run_writer
from job_agent.memory.store import Store
from job_agent.schemas import GeneratedApplication, JobPosting, MatchResult, UserProfile
from job_agent.tools.job_search import extract_skill_mentions, parse_salary_range
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

INBOX_FILENAME = "inbox.json"
_ALLOWED_STATUS = {"neu", "bewertet", "verworfen"}
_INBOX_LOCK = threading.RLock()
_MAX_INBOX_ITEMS = 500
_MAX_INBOX_BYTES = 2 * 1024 * 1024
_MAX_URL_CHARS = 2048
_MAX_DESCRIPTION_CHARS = 100_000

# Section headers that usually introduce the requirements block of a German
# or English job ad. Bullets below such a header are treated as requirements.
_REQUIREMENT_HEADERS = (
    "anforderung",
    "dein profil",
    "ihr profil",
    "profil",
    "qualifikation",
    "das bringst du mit",
    "was du mitbringst",
    "requirements",
    "your profile",
    "qualifications",
    "what you bring",
)
_BULLET_RE = re.compile(r"^\s*[-*•▪-]\s+(.{2,120})$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
ManualSource = Literal["indeed", "stepstone", "linkedin", "xing", "manual"]
_PORTAL_HOSTS: tuple[tuple[str, ManualSource], ...] = (
    ("indeed.com", "indeed"),
    ("stepstone.de", "stepstone"),
    ("linkedin.com", "linkedin"),
    ("xing.com", "xing"),
)


def inbox_path(data_root: str | Path) -> Path:
    return Path(data_root) / INBOX_FILENAME


def load_inbox(path: str | Path) -> list[dict[str, Any]]:
    """Read all inbox items (newest first). Missing/broken file ⇒ empty list."""
    with _INBOX_LOCK:
        return _load_inbox_unlocked(path)


def _load_inbox_unlocked(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.exists():
        return []
    try:
        if file.stat().st_size > _MAX_INBOX_BYTES:
            log.warning("[inbox] %s ist zu gross — ignoriere Inhalt", file)
            return []
    except OSError:
        return []
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("[inbox] %s ist nicht lesbar — starte leer", file)
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("id")]


def add_item(path: str | Path, url: str, note: str = "") -> dict[str, Any]:
    """Add a URL to the inbox (idempotent per URL — re-adding refreshes the note)."""
    cleaned = url.strip()
    if not _URL_RE.match(cleaned) or len(cleaned) > _MAX_URL_CHARS:
        raise ValueError("Bitte eine vollständige URL angeben (https://…).")
    with _INBOX_LOCK:
        items = _load_inbox_unlocked(path)
        item_id = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:12]
        existing = next((item for item in items if item.get("id") == item_id), None)
        if existing is not None:
            if note:
                existing["note"] = note.strip()[:300]
            _save_unlocked(path, items)
            return existing
        item = {
            "id": item_id,
            "url": cleaned,
            "note": note.strip()[:300],
            "status": "neu",
            "added_at": datetime.now().isoformat(timespec="seconds"),
            "job_id": None,
        }
        items.insert(0, item)
        _save_unlocked(path, items[:_MAX_INBOX_ITEMS])
    log.info("[inbox] gemerkt: %s", cleaned)
    return item


def update_status(
    path: str | Path, item_id: str, status: str, job_id: str | None = None
) -> dict[str, Any]:
    if status not in _ALLOWED_STATUS:
        raise ValueError(f"Unbekannter Status '{status}'. Erlaubt: {', '.join(sorted(_ALLOWED_STATUS))}.")
    with _INBOX_LOCK:
        items = _load_inbox_unlocked(path)
        for item in items:
            if item.get("id") == item_id:
                item["status"] = status
                if job_id:
                    item["job_id"] = job_id[:200]
                _save_unlocked(path, items)
                return item
    raise ValueError(f"Inbox-Eintrag '{item_id}' nicht gefunden.")


def remove_item(path: str | Path, item_id: str) -> bool:
    with _INBOX_LOCK:
        items = _load_inbox_unlocked(path)
        remaining = [item for item in items if item.get("id") != item_id]
        if len(remaining) == len(items):
            return False
        _save_unlocked(path, remaining)
        return True


def posting_from_text(
    *,
    title: str,
    company: str = "",
    location: str = "",
    description: str,
    url: str = "",
) -> JobPosting:
    """Turn a pasted job ad into a validated manual :class:`JobPosting`.

    Requirements are extracted conservatively: bullet lines below a
    requirements-style header first, any bullet lines second, and a compact
    tech-keyword scan as the last resort. Nothing is invented — an ad without
    recognizable requirements simply yields an empty list (the Matcher rates
    that as "keine strukturierten Muss-Skills").
    """
    text = description.strip()
    if len(text) < 40:
        raise ValueError("Der Anzeigentext ist zu kurz — bitte die komplette Anzeige einfügen.")
    if len(text) > _MAX_DESCRIPTION_CHARS:
        raise ValueError("Der Anzeigentext ist zu lang (maximal 100.000 Zeichen).")
    cleaned_title = title.strip() or "Unbenannte Stelle"
    requirements, nice_to_have = _extract_requirements(text)
    source = _source_from_url(url)
    source_key = url or hashlib.sha256(text.encode("utf-8")).hexdigest()
    job_id = hashlib.sha1(
        f"{source}|{source_key}|{cleaned_title}|{company}".encode()
    ).hexdigest()[:16]
    return JobPosting(
        id=job_id,
        source=source,
        source_id=job_id,
        url=url.strip() or "https://manual.local/inbox",  # type: ignore[arg-type]
        title=cleaned_title[:120],
        company=company.strip() or "Unbekanntes Unternehmen",
        location=location.strip() or "Unbekannt",
        description=text,
        requirements_raw=text,
        requirements=requirements,
        nice_to_have=nice_to_have,
        salary_range=parse_salary_range(text),
    )


def _source_from_url(url: str) -> ManualSource:
    """Attribute a user-pasted URL without fetching or automating the portal."""
    host = (urlparse(url.strip()).hostname or "").lower().rstrip(".")
    for suffix, source in _PORTAL_HOSTS:
        if host == suffix or host.endswith(f".{suffix}"):
            return source
    return "manual"


def evaluate_pasted_job(
    store: Store,
    profile: UserProfile,
    posting: JobPosting,
    *,
    threshold: float = 0.5,
    use_llm: bool = False,
) -> tuple[MatchResult, GeneratedApplication | None]:
    """Single-job auto-pipeline: persist → match → (optionally) draft + track."""
    store.save_job(posting)
    profile_fingerprint = store.save_profile(profile, "inbox")
    [match] = run_matcher([posting], profile, threshold=threshold, use_llm=use_llm)
    store.save_match(match, profile_fingerprint)
    application: GeneratedApplication | None = None
    if match.score >= threshold and not store.job_exists(posting.id):
        application = run_writer(posting, match, profile, use_llm=use_llm)
        run_tracker(application=application, store=store, status="draft")
    log.info(
        "[inbox] bewertet: %s -> score=%.2f, entwurf=%s",
        posting.title,
        match.score,
        "ja" if application else "nein",
    )
    return match, application


def _extract_requirements(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    lowered = [line.strip().lower() for line in lines]

    # 1) Bullets below a requirements-style header, until the next header-ish line.
    in_block = False
    block: list[str] = []
    for line, low in zip(lines, lowered, strict=True):
        if any(header in low for header in _REQUIREMENT_HEADERS) and len(low) < 60:
            in_block = True
            continue
        if in_block:
            bullet = _BULLET_RE.match(line)
            if bullet:
                block.append(bullet.group(1).strip().rstrip("."))
            elif low and not bullet and len(low) < 60 and low.endswith(":"):
                in_block = False
    if block:
        return extract_skill_mentions("\n".join(block))

    # 2) Any bullet lines in the ad.
    bullets = [m.group(1).strip().rstrip(".") for line in lines if (m := _BULLET_RE.match(line))]
    if bullets:
        return extract_skill_mentions("\n".join(bullets))

    # 3) Keyword scan (last resort, conservative).
    requirements, nice_to_have = extract_skill_mentions(text)
    return requirements[:10], nice_to_have[:10]


def _save_unlocked(path: str | Path, items: list[dict[str, Any]]) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"items": items[:_MAX_INBOX_ITEMS]}, ensure_ascii=False, indent=2
    ).encode("utf-8")
    if len(payload) > _MAX_INBOX_BYTES:
        raise ValueError("Inbox-Daten überschreiten das Speicherlimit.")
    fd, temp_name = tempfile.mkstemp(prefix=".inbox-", suffix=".tmp", dir=file.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, file)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
