"""Matcher agent — scores each posting against the user's profile.

Sprint 1 implementation: deterministic skill overlap, no LLM. Sprint 3 swaps
the scoring function for an LLM-backed semantic match while keeping the same
input/output schema.
"""

from __future__ import annotations

from job_agent.schemas import JobPosting, MatchResult, UserProfile
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def _normalize(skills: list[str]) -> set[str]:
    return {s.strip().lower() for s in skills if s.strip()}


def run_matcher(
    jobs: list[JobPosting],
    profile: UserProfile,
    threshold: float = 0.6,
) -> list[MatchResult]:
    """Score every job against the profile.

    Scoring (Sprint 1, intentionally simple):
        matched = |required ∩ profile_skills|
        score   = matched / max(|required|, 1)
        bonus   = +0.1 if any nice_to_have is matched (capped at 1.0)

    The threshold isn't enforced here — pipeline.py uses it to decide which
    matches go to the Writer. Sprint 3 replaces this with an LLM call that
    can reason about transferable skills.
    """
    profile_skills = _normalize(profile.skills)
    results: list[MatchResult] = []

    for job in jobs:
        required = _normalize(job.requirements)
        nice = _normalize(job.nice_to_have)

        matched = sorted(required & profile_skills)
        missing = sorted(required - profile_skills)

        base = len(matched) / max(len(required), 1)
        bonus = 0.1 if (nice & profile_skills) else 0.0
        score = min(base + bonus, 1.0)

        rationale = (
            f"{len(matched)}/{len(required)} required skills matched"
            f"{' (+bonus for nice-to-have overlap)' if bonus else ''}. "
            f"Missing: {', '.join(missing) if missing else 'none'}."
        )

        result = MatchResult(
            job_id=job.id,
            score=round(score, 3),
            matched_skills=matched,
            missing_skills=missing,
            rationale=rationale,
        )
        log.info("[matcher] %s → score=%.2f", job.id, result.score)
        results.append(result)

    return results
