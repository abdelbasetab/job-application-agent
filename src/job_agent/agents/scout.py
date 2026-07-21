"""Scout agent — discovers validated postings from real job-search sources.

The Scout deliberately orchestrates Adzuna and BA-Jobsuche in deterministic
application code.  An LLM is not allowed to choose, rewrite, or invent source
records; Matcher and Writer can still use the configured LLM after the jobs
have crossed this trust boundary.
"""

from __future__ import annotations

import json
from typing import Any

from job_agent.schemas import JobPosting, UserProfile
from job_agent.tools.job_search import search_all
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def _dedup(postings: list[JobPosting]) -> list[JobPosting]:
    """Stable-order deduplication by the canonical posting id."""
    seen: set[str] = set()
    out: list[JobPosting] = []
    for posting in postings:
        if posting.id in seen:
            continue
        seen.add(posting.id)
        out.append(posting)
    return out


def _verify_tool_postings(
    raw_items: list[dict[str, Any]], tool_results: list[JobPosting]
) -> list[JobPosting]:
    """Accept only byte-equivalent records from an authoritative tool ledger.

    Kept as a reusable trust-boundary helper for any future orchestrator.  The
    current Scout returns source-tool objects directly and therefore does not
    need to round-trip them through an LLM.
    """

    def fingerprint(posting: JobPosting) -> str:
        return json.dumps(
            posting.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    allowed = {fingerprint(posting): posting for posting in tool_results}
    verified: list[JobPosting] = []
    for item in raw_items:
        if not isinstance(item, dict):
            log.warning("[scout] dropping non-object orchestrator output")
            continue
        try:
            candidate = JobPosting.model_validate(item)
        except Exception as exc:
            log.warning("[scout] dropping invalid orchestrator posting: %s", exc)
            continue
        authoritative = allowed.get(fingerprint(candidate))
        if authoritative is None:
            log.warning("[scout] dropping posting absent from tool ledger: %s", candidate.id)
            continue
        verified.append(authoritative)
    return _dedup(verified)


def _direct_scout(
    profile: UserProfile, query: str | None = None, limit: int = 5
) -> list[JobPosting]:
    """Query both supported boards and return their validated source objects."""
    if not 1 <= limit <= 25:
        raise ValueError("Scout limit must be between 1 and 25.")
    search_hint = (query or " ".join(profile.skills[:3]) or "software").strip()[:500]
    extra = [skill[:200] for skill in profile.skills[:3] if skill.strip()]
    postings = search_all(
        query=search_hint,
        location="Germany",
        limit=max(limit, 5),
        extra_queries=extra,
        adzuna_pages=2,
        enrich=True,
    )
    return _dedup(postings)[:limit]


def run_scout(
    profile: UserProfile, query: str | None = None, limit: int = 5
) -> list[JobPosting]:
    """Discover real jobs without allowing generative output into the source set."""
    log.info("[scout] deterministic multi-board search profile=%s limit=%d", profile.name, limit)
    postings = _direct_scout(profile, query, limit)
    if not postings:
        raise RuntimeError(
            "Scout produced no postings — Adzuna and BA-Jobsuche returned empty "
            "or unusable results. Check API credentials and network."
        )
    return postings
