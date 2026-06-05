"""Job-board adapters for Scout.

Sprint 2: real HTTP implementations against Adzuna and the Bundesagentur für
Arbeit Jobsuche-API. Each function returns validated `JobPosting` instances.

Errors are caught and logged, never raised: a failing adapter returns []. The
caller (Scout) decides what to do when *all* sources fail.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import httpx

from job_agent.schemas import JobPosting
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

_USER_AGENT = "JobApplicationAgent/1.0"
_HTTP_TIMEOUT = 15.0


def _stable_id(source: str, source_id: str) -> str:
    """JobPosting.id — short SHA1 of (source, source_id) for dedup."""
    digest = hashlib.sha1(f"{source}:{source_id}".encode("utf-8")).hexdigest()
    return digest[:16]


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


# ────────────────────────────────────────────────────────────────────────────
# Adzuna
# ────────────────────────────────────────────────────────────────────────────
_ADZUNA_CONTRACT_TIME = {
    "full_time": "full-time",
    "part_time": "part-time",
}


def _adzuna_normalize(item: dict[str, Any]) -> JobPosting | None:
    """Map one Adzuna result dict into a validated JobPosting (or None)."""
    source = "adzuna"
    source_id = str(item.get("id") or "").strip()
    url = (item.get("redirect_url") or "").strip()
    title = (item.get("title") or "").strip()
    company = ((item.get("company") or {}).get("display_name") or "").strip()
    location = ((item.get("location") or {}).get("display_name") or "").strip()
    description = (item.get("description") or "").strip()

    if not (source_id and url.startswith("https://") and title and company):
        return None

    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")
    salary: tuple[int, int] | None = None
    if isinstance(salary_min, (int, float)) and isinstance(salary_max, (int, float)):
        salary = (int(salary_min), int(salary_max))

    employment_type = _ADZUNA_CONTRACT_TIME.get(
        (item.get("contract_time") or "").lower()
    )

    try:
        return JobPosting(
            id=_stable_id(source, source_id),
            source=source,
            source_id=source_id,
            url=url,  # type: ignore[arg-type]
            title=title,
            company=company,
            location=location or "Germany",
            posted_at=_parse_iso_date(item.get("created")),
            description=description,
            requirements_raw=description,
            requirements=[],
            nice_to_have=[],
            salary_range=salary,
            employment_type=employment_type,  # type: ignore[arg-type]
            remote=None,
        )
    except Exception as exc:
        log.warning("[adzuna] dropping invalid posting %s: %s", source_id, exc)
        return None


def adzuna_search(
    query: str,
    location: str = "Germany",
    limit: int = 20,
) -> list[JobPosting]:
    """Search Adzuna and return validated JobPosting items.

    Requires ADZUNA_APP_ID and ADZUNA_APP_KEY in .env. On any HTTP error,
    logs and returns []. The caller may fall back to other sources.
    """
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        log.warning("[adzuna] missing credentials in .env — returning []")
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/{settings.adzuna_country}/search/1"
    params = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "results_per_page": limit,
        "what": query,
        "where": location,
        "content-type": "application/json",
    }
    log.info("[adzuna] GET %s what=%r where=%r limit=%d", url, query, location, limit)

    try:
        response = httpx.get(url, params=params, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("[adzuna] HTTP error: %s", exc)
        return []

    raw_results = response.json().get("results", [])
    postings = [p for item in raw_results if (p := _adzuna_normalize(item)) is not None]
    log.info(
        "[adzuna] %d raw → %d validated postings", len(raw_results), len(postings)
    )
    return postings[:limit]


# ────────────────────────────────────────────────────────────────────────────
# Bundesagentur für Arbeit — Jobsuche
# ────────────────────────────────────────────────────────────────────────────
def _ba_normalize(item: dict[str, Any]) -> JobPosting | None:
    """Map one BA-Jobsuche `stellenangebot` into a validated JobPosting."""
    source = "ba-jobsuche"
    source_id = str(item.get("refnr") or "").strip()
    if not source_id:
        return None

    title = (item.get("titel") or item.get("beruf") or "").strip()
    company = (item.get("arbeitgeber") or "").strip()

    arbeitsort = item.get("arbeitsort") or {}
    if isinstance(arbeitsort, list) and arbeitsort:
        arbeitsort = arbeitsort[0]
    location = ""
    if isinstance(arbeitsort, dict):
        location = (arbeitsort.get("ort") or "").strip()

    url = (item.get("externeUrl") or "").strip()
    if not url.startswith("https://"):
        url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{source_id}"

    if not (title and company):
        return None

    try:
        return JobPosting(
            id=_stable_id(source, source_id),
            source=source,
            source_id=source_id,
            url=url,  # type: ignore[arg-type]
            title=title,
            company=company,
            location=location or "Germany",
            posted_at=_parse_iso_date(item.get("aktuelleVeroeffentlichungsdatum")),
            description="",
            requirements_raw="",
            requirements=[],
            nice_to_have=[],
            salary_range=None,
            employment_type=None,
            remote=None,
        )
    except Exception as exc:
        log.warning("[ba-jobsuche] dropping invalid posting %s: %s", source_id, exc)
        return None


def ba_jobsuche_search(
    query: str,
    location: str = "",
    limit: int = 20,
) -> list[JobPosting]:
    """Search the Bundesagentur für Arbeit Jobsuche-API.

    No API key required, but a descriptive User-Agent header is mandatory.
    Returns validated JobPosting items; logs and returns [] on HTTP errors.
    """
    url = f"{settings.ba_jobsuche_base_url}/jobs"
    params: dict[str, Any] = {"was": query, "size": limit}
    if location:
        params["wo"] = location

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        "X-API-Key": settings.ba_jobsuche_api_key,
    }
    log.info("[ba-jobsuche] GET %s was=%r wo=%r size=%d", url, query, location, limit)

    try:
        response = httpx.get(
            url, params=params, headers=headers, timeout=_HTTP_TIMEOUT
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("[ba-jobsuche] HTTP error: %s", exc)
        return []

    raw_results = response.json().get("stellenangebote", [])
    postings = [p for item in raw_results if (p := _ba_normalize(item)) is not None]
    log.info(
        "[ba-jobsuche] %d raw → %d validated postings",
        len(raw_results),
        len(postings),
    )
    return postings[:limit]
