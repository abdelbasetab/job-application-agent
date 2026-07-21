"""Job-board adapters for Scout.

HTTP implementations for Adzuna and the Bundesagentur für Arbeit Jobsuche-API.
Each function returns validated :class:`JobPosting` instances.

Errors are caught and logged, never raised: a failing adapter returns []. The
caller (Scout) decides what to do when *all* sources fail.
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import date
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from job_agent.schemas import JobPosting
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

_USER_AGENT = "JobApplicationAgent/1.0"
_HTTP_TIMEOUT = 15.0
_MAX_DESCRIPTION_CHARS = 200_000
_SALARY_RANGE_RE = re.compile(
    r"(?P<low>\d{2,3}(?:[.\s]\d{3})|\d{5,6})\s*"
    r"(?:-|\u2013|\u2014|bis|to)\s*"
    r"(?P<high>\d{2,3}(?:[.\s]\d{3})|\d{5,6})\s*"
    r"(?:€|eur|euro)?",
    re.IGNORECASE,
)
_NICE_TO_HAVE_CUES = (
    "nice to have",
    "preferred",
    "bonus",
    "plus",
    "von vorteil",
    "wuenschenswert",
    "idealerweise",
)
_SKILL_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("python", ("python",)),
    ("sql", ("sql", "postgresql", "postgres", "mysql", "sqlite", "mssql")),
    ("git", ("git", "github", "gitlab")),
    ("llms", ("llm", "llms", "large language model", "large language models", "gpt")),
    ("rag", ("rag", "retrieval augmented generation", "retrieval-augmented generation")),
    ("machine learning", ("machine learning", "ml", "ki modelle", "ki-modelle")),
    ("data analysis", ("data analysis", "datenanalyse", "analytics", "reporting")),
    ("pandas", ("pandas",)),
    ("numpy", ("numpy",)),
    ("scikit-learn", ("scikit-learn", "sklearn")),
    ("pytorch", ("pytorch", "torch")),
    ("tensorflow", ("tensorflow",)),
    ("docker", ("docker", "container")),
    ("kubernetes", ("kubernetes", "k8s")),
    ("linux", ("linux",)),
    ("windows", ("windows",)),
    ("rest apis", ("rest api", "rest apis", "restful", "api development", "api-entwicklung")),
    ("fastapi", ("fastapi",)),
    ("flask", ("flask",)),
    ("django", ("django",)),
    ("javascript", ("javascript", "js")),
    ("typescript", ("typescript", "ts")),
    ("react", ("react", "react.js", "reactjs")),
    ("node.js", ("node.js", "nodejs")),
    ("html", ("html",)),
    ("css", ("css",)),
    ("java", ("java",)),
    ("aws", ("aws", "amazon web services")),
    ("azure", ("azure",)),
    ("gcp", ("gcp", "google cloud")),
    ("excel", ("excel",)),
    ("scrum", ("scrum",)),
    ("agile", ("agile",)),
)


def _stable_id(source: str, source_id: str) -> str:
    """JobPosting.id — short SHA1 of (source, source_id) for dedup."""
    digest = hashlib.sha1(f"{source}:{source_id}".encode()).hexdigest()
    return digest[:16]


def _clean_string(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:maximum]


def _parse_iso_date(value: object) -> date | None:
    cleaned = _clean_string(value, 40)
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned[:10])
    except ValueError:
        return None


def parse_salary_range(value: str | None) -> tuple[int, int] | None:
    """Parse common annual German salary ranges like '50.000 - 70.000 EUR'."""
    if not value:
        return None
    match = _SALARY_RANGE_RE.search(value)
    if not match:
        return None

    def normalize(raw: str) -> int:
        return int(raw.replace(".", "").replace(" ", ""))

    low = normalize(match.group("low"))
    high = normalize(match.group("high"))
    if low > high:
        low, high = high, low
    if low < 10000 or high > 300000:
        return None
    return (low, high)


def extract_skill_mentions(text: str) -> tuple[list[str], list[str]]:
    """Extract known technical skills from free-text job descriptions.

    This is deliberately conservative and deterministic. It gives the fallback
    matcher useful structure for live API jobs without asking an LLM to parse
    every posting.
    """
    lowered = text.lower()
    requirements: list[str] = []
    nice_to_have: list[str] = []

    for canonical, aliases in _SKILL_ALIASES:
        for alias in aliases:
            pattern = _alias_pattern(alias)
            match = re.search(pattern, lowered)
            if match is None:
                continue
            window = _sentence_window(lowered, match.start(), match.end())
            if any(cue in window for cue in _NICE_TO_HAVE_CUES):
                nice_to_have.append(canonical)
            else:
                requirements.append(canonical)
            break

    return _dedup(requirements), _dedup(nice_to_have)


def _alias_pattern(alias: str) -> str:
    escaped = re.escape(alias.lower()).replace(r"\ ", r"[\s-]+")
    return rf"(?<![a-z0-9+#]){escaped}(?![a-z0-9+#])"


def _sentence_window(text: str, start: int, end: int) -> str:
    left_candidates = [text.rfind(mark, 0, start) for mark in (".", ";", "\n")]
    right_candidates = [
        pos for mark in (".", ";", "\n") if (pos := text.find(mark, end)) != -1
    ]
    left = max(left_candidates) + 1
    right = min(right_candidates) if right_candidates else len(text)
    return text[left:right]


def _dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _hydrate_requirements(posting: JobPosting) -> JobPosting:
    text = posting.requirements_raw or posting.description
    if not text:
        return posting
    requirements, nice_to_have = extract_skill_mentions(text)
    if requirements and not posting.requirements:
        posting.requirements = requirements
    if nice_to_have and not posting.nice_to_have:
        posting.nice_to_have = nice_to_have
    if not posting.requirements_raw and posting.description:
        posting.requirements_raw = posting.description
    return posting


def _response_object(response: httpx.Response, source: str) -> dict[str, Any] | None:
    """Decode a board response without letting malformed JSON escape the adapter."""
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        log.error("[%s] invalid JSON response: %s", source, exc)
        return None
    if not isinstance(payload, dict):
        log.error("[%s] expected a JSON object, got %s", source, type(payload).__name__)
        return None
    return payload


def _canonical_url(value: object) -> str:
    """Normalize a posting URL while discarding common tracking parameters."""
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower().removeprefix("www.")
    port = parsed.port
    if port and not (
        (parsed.scheme.lower() == "https" and port == 443)
        or (parsed.scheme.lower() == "http" and port == 80)
    ):
        host = f"{host}:{port}"
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=False)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"ref", "source", "tracking", "trk", "cid"}
        )
    )
    return urlunsplit((parsed.scheme.lower(), host, path, query, ""))


def _identity_key(posting: JobPosting) -> tuple[str, str, str]:
    def fold(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    return fold(posting.title), fold(posting.company), fold(posting.location)


# ────────────────────────────────────────────────────────────────────────────
# Adzuna
# ────────────────────────────────────────────────────────────────────────────
_ADZUNA_CONTRACT_TIME = {
    "full_time": "full-time",
    "part_time": "part-time",
}


def _adzuna_normalize(item: dict[str, Any]) -> JobPosting | None:
    """Map one Adzuna result dict into a validated JobPosting (or None)."""
    source: Literal["adzuna"] = "adzuna"
    source_id = str(item.get("id") or "").strip()
    url = _clean_string(item.get("redirect_url"), 2_083)
    title = _clean_string(item.get("title"), 500)
    company_data = item.get("company")
    location_data = item.get("location")
    company = _clean_string(
        company_data.get("display_name") if isinstance(company_data, dict) else None,
        500,
    )
    location = _clean_string(
        location_data.get("display_name") if isinstance(location_data, dict) else None,
        500,
    )
    description = _clean_string(item.get("description"), _MAX_DESCRIPTION_CHARS)

    if not (source_id and url.startswith("https://") and title and company):
        return None

    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")
    salary: tuple[int, int] | None = None
    if isinstance(salary_min, (int, float)) and isinstance(salary_max, (int, float)):
        low, high = sorted((int(salary_min), int(salary_max)))
        if low >= 0:
            salary = (low, high)
    if salary is None:
        salary = parse_salary_range(description)

    employment_type = _ADZUNA_CONTRACT_TIME.get(
        _clean_string(item.get("contract_time"), 100).lower()
    )

    try:
        posting = JobPosting(
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
        return _hydrate_requirements(posting)
    except Exception as exc:
        log.warning("[adzuna] dropping invalid posting %s: %s", source_id, exc)
        return None


def adzuna_search(
    query: str,
    location: str = "Germany",
    limit: int = 20,
    page: int = 1,
) -> list[JobPosting]:
    """Search Adzuna and return validated JobPosting items.

    Requires ADZUNA_APP_ID and ADZUNA_APP_KEY in .env. On any HTTP error,
    logs and returns []. The caller may fall back to other sources.
    """
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        log.warning("[adzuna] missing credentials in .env — returning []")
        return []

    query = query.strip()[:200]
    location = location.strip()[:120]
    limit = max(1, min(50, int(limit)))
    page = max(1, min(50, int(page)))
    if not query:
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/{settings.adzuna_country}/search/{page}"
    params: dict[str, str | int] = {
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

    payload = _response_object(response, "adzuna")
    if payload is None:
        return []
    raw_results = payload.get("results", [])
    if not isinstance(raw_results, list):
        log.error("[adzuna] 'results' is not an array")
        return []
    postings = [
        p
        for item in raw_results[: max(50, limit * 2)]
        if isinstance(item, dict) and (p := _adzuna_normalize(item)) is not None
    ]
    log.info(
        "[adzuna] %d raw → %d validated postings", len(raw_results), len(postings)
    )
    return postings[:limit]


# ────────────────────────────────────────────────────────────────────────────
# Bundesagentur für Arbeit — Jobsuche
# ────────────────────────────────────────────────────────────────────────────
def _ba_normalize(item: dict[str, Any]) -> JobPosting | None:
    """Map one BA-Jobsuche `stellenangebot` into a validated JobPosting."""
    source: Literal["ba-jobsuche"] = "ba-jobsuche"
    source_id = str(item.get("refnr") or "").strip()
    if not source_id:
        return None

    title = _clean_string(item.get("titel") or item.get("beruf"), 500)
    company = _clean_string(item.get("arbeitgeber"), 500)

    arbeitsort = item.get("arbeitsort") or {}
    if isinstance(arbeitsort, list) and arbeitsort:
        arbeitsort = arbeitsort[0]
    location = ""
    if isinstance(arbeitsort, dict):
        location = _clean_string(arbeitsort.get("ort"), 500)

    url = _clean_string(item.get("externeUrl"), 2_083)
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
    *,
    enrich: bool = False,
) -> list[JobPosting]:
    """Search the Bundesagentur für Arbeit Jobsuche-API.

    No API key required, but a descriptive User-Agent header is mandatory.
    Returns validated JobPosting items; logs and returns [] on HTTP errors.
    """
    query = query.strip()[:200]
    location = location.strip()[:120]
    limit = max(1, min(50, int(limit)))
    if not query:
        return []
    url = f"{settings.ba_jobsuche_base_url}/jobs"
    params: dict[str, str | int] = {"was": query, "size": limit}
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

    payload = _response_object(response, "ba-jobsuche")
    if payload is None:
        return []
    raw_results = payload.get("stellenangebote", [])
    if not isinstance(raw_results, list):
        log.error("[ba-jobsuche] 'stellenangebote' is not an array")
        return []
    postings = [
        p
        for item in raw_results[: max(50, limit * 2)]
        if isinstance(item, dict) and (p := _ba_normalize(item)) is not None
    ]
    log.info(
        "[ba-jobsuche] %d raw → %d validated postings",
        len(raw_results),
        len(postings),
    )
    postings = postings[:limit]
    if enrich:
        _enrich_descriptions(postings)
    return postings


# ────────────────────────────────────────────────────────────────────────────
# Combined deterministic search (no LLM) — Scout's robust fallback
# ────────────────────────────────────────────────────────────────────────────
def ba_jobsuche_detail(refnr: str) -> str:
    """Fetch a BA posting's full description via the official detail API.

    The list endpoint returns no description; the detail endpoint does
    (field ``stellenangebotsBeschreibung``). Returns "" on any error.
    """
    if not refnr:
        return ""
    encoded = base64.b64encode(refnr.encode("utf-8")).decode("ascii")
    url = f"{settings.ba_jobsuche_base_url}/jobdetails/{encoded}"
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        "X-API-Key": settings.ba_jobsuche_api_key,
    }
    try:
        response = httpx.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("[ba-jobsuche] detail HTTP error for %s: %s", refnr, exc)
        return ""
    data = _response_object(response, "ba-jobsuche-detail")
    if data is None:
        return ""
    return _clean_string(
        data.get("stellenangebotsBeschreibung"), _MAX_DESCRIPTION_CHARS
    )


def _enrich_descriptions(postings: list[JobPosting]) -> list[JobPosting]:
    """Backfill empty descriptions: BA detail API first, optional scraper second."""
    for posting in postings:
        if not posting.description.strip():
            text = ""
            if posting.source == "ba-jobsuche":
                text = ba_jobsuche_detail(posting.source_id)
            if not text and settings.enable_scraper:
                from job_agent.tools.scraper import scrape_job_text

                text = scrape_job_text(str(posting.url))
            if text:
                posting.description = text
                if not posting.requirements_raw:
                    posting.requirements_raw = text
        _hydrate_requirements(posting)
    return postings


def search_all(
    query: str,
    location: str = "Germany",
    limit: int = 20,
    *,
    extra_queries: list[str] | None = None,
    adzuna_pages: int = 1,
    enrich: bool = False,
) -> list[JobPosting]:
    """Query both boards and deduplicate IDs, canonical URLs and cross-source jobs.

    Needs no LLM/tool-calling, so it works against any provider. Scout uses it
    as the Scout's deterministic multi-source orchestration path.

    ``extra_queries`` broadens the search (e.g. profile skills); ``adzuna_pages``
    pages through Adzuna; ``enrich`` backfills missing descriptions (BA detail
    API + optional scraper) so the matcher has real text to work with.
    """
    queries: list[str] = []
    for candidate in [query, *(extra_queries or [])][:6]:
        cleaned = (candidate or "").strip()
        if cleaned and cleaned not in queries:
            queries.append(cleaned)

    combined: list[JobPosting] = []
    for q in queries:
        for page in range(1, max(1, min(int(adzuna_pages), 5)) + 1):
            combined += adzuna_search(query=q, location=location, limit=limit, page=page)
        combined += ba_jobsuche_search(query=q, location="", limit=limit)

    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    identity_sources: dict[tuple[str, str, str], str] = {}
    merged: list[JobPosting] = []
    for posting in combined:
        canonical_url = _canonical_url(posting.url)
        identity = _identity_key(posting)
        previous_source = identity_sources.get(identity)
        if posting.id in seen_ids or (canonical_url and canonical_url in seen_urls):
            continue
        # Two different boards frequently advertise the same role under different
        # URLs and IDs. Exact normalized title/company/location is conservative
        # enough to collapse that case while retaining same-board vacancies.
        if all(identity) and previous_source is not None and previous_source != posting.source:
            continue
        seen_ids.add(posting.id)
        if canonical_url:
            seen_urls.add(canonical_url)
        if all(identity):
            identity_sources.setdefault(identity, posting.source)
        merged.append(posting)
    merged = merged[:limit]
    log.info(
        "[search_all] %d queries -> %d combined -> %d after dedup/limit",
        len(queries),
        len(combined),
        len(merged),
    )
    if enrich:
        _enrich_descriptions(merged)
    return merged
