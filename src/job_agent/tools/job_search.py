"""Job-board adapters for Scout.

Sprint 1 ships only a stub. Sprint 2 wires up Adzuna and BA-Jobsuche.

Both functions return raw dicts; normalization into `JobPosting` happens in
the Scout agent itself, so the Scout retains full control over what gets
into the schema (no silent passthrough).
"""

from __future__ import annotations

from typing import Any

import httpx

from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Sprint 2 — Adzuna
# ────────────────────────────────────────────────────────────────────────────
def adzuna_search(query: str, location: str = "Germany", limit: int = 20) -> list[dict[str, Any]]:
    """Search the Adzuna API.

    Requires ADZUNA_APP_ID and ADZUNA_APP_KEY in .env. Returns the raw
    `results` array — Scout is responsible for mapping each entry to a
    JobPosting (so Sprint-2 testing can mock just this function).
    """
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        log.warning("[adzuna] no credentials in .env — returning []")
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
    r = httpx.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("results", [])


# ────────────────────────────────────────────────────────────────────────────
# Sprint 2 — Bundesagentur für Arbeit Jobsuche-API
# ────────────────────────────────────────────────────────────────────────────
def ba_jobsuche_search(
    query: str, location: str = "", limit: int = 20
) -> list[dict[str, Any]]:
    """Search the Bundesagentur für Arbeit Jobsuche-API.

    No API key required. The BA endpoint demands a User-Agent header; pass
    a descriptive one so they can contact us if we misbehave.
    """
    url = f"{settings.ba_jobsuche_base_url}/jobs"
    params = {"was": query, "wo": location, "size": limit}
    headers = {
        "User-Agent": "job-application-agent/0.1 (student-project; contact@example.com)",
        "Accept": "application/json",
    }
    r = httpx.get(url, params=params, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json().get("stellenangebote", [])
