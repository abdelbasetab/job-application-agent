"""Matcher agent — scores each posting against the user's profile.

Sprint 3 adds an optional LLM-backed semantic matcher. The deterministic
skill-overlap scorer remains as a fallback so offline demos and tests stay
stable when no local/cloud LLM is available.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_agent.schemas import JobPosting, MatchResult, UserProfile
from job_agent.utils.config import settings
from job_agent.utils.llm import call_llm
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "matcher.md"


def _normalize(skills: list[str]) -> set[str]:
    return {s.strip().lower() for s in skills if s.strip()}


def run_matcher(
    jobs: list[JobPosting],
    profile: UserProfile,
    threshold: float = 0.6,
    use_llm: bool | None = None,
    profile_context: list[str] | None = None,
) -> list[MatchResult]:
    """Score every job against the profile.

    When `use_llm` is true, each job is sent to the configured LLM with the
    Sprint-3 matcher prompt. Invalid or failed LLM calls fall back to the
    deterministic overlap scorer for that job.
    """
    llm_enabled = settings.enable_llm_agents if use_llm is None else use_llm
    if llm_enabled:
        return [
            _run_llm_matcher(job, profile, threshold, profile_context)
            for job in jobs
        ]
    return [_run_deterministic_match(job, profile) for job in jobs]


def _run_deterministic_match(job: JobPosting, profile: UserProfile) -> MatchResult:
    profile_skills = _normalize(profile.skills)
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
    return result


def _run_llm_matcher(
    job: JobPosting,
    profile: UserProfile,
    threshold: float,
    profile_context: list[str] | None,
) -> MatchResult:
    try:
        prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        user_payload = {
            "job": job.model_dump(mode="json"),
            "profile": profile.model_dump(mode="json"),
            "profile_context": profile_context or [],
            "threshold_hint": threshold,
        }
        raw = call_llm(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "Return only one JSON object matching MatchResult.\n"
                        f"{json.dumps(user_payload, ensure_ascii=False)}"
                    ),
                },
            ]
        )
        result = _parse_match(raw, expected_job_id=job.id)
        log.info("[matcher:llm] %s → score=%.2f", job.id, result.score)
        return result
    except Exception as exc:
        log.warning("[matcher:llm] falling back for %s: %s", job.id, exc)
        fallback = _run_deterministic_match(job, profile)
        if not fallback.rationale.startswith("LLM fallback:"):
            fallback.rationale = f"LLM fallback: {fallback.rationale}"
        return fallback


def _parse_match(raw: Any, expected_job_id: str) -> MatchResult:
    if isinstance(raw, MatchResult):
        return raw
    if not isinstance(raw, str):
        raise TypeError(f"expected string LLM output, got {type(raw)!r}")
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM matcher output was not a JSON object")
    data["job_id"] = data.get("job_id") or expected_job_id
    return MatchResult.model_validate(data)
