"""Profiler agent — turns a raw CV (Lebenslauf) into a structured UserProfile.

This is the new front of the pipeline for Sprint 3: instead of a baked-in demo
profile, the candidate's actual CV is read (``utils.cv.extract_cv_text``) and
handed to the configured LLM, which extracts a validated :class:`UserProfile`.

It needs an LLM — parsing arbitrary CV prose deterministically is out of scope.
Users without a provider can supply a YAML profile instead (``--profile``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_agent.schemas import UserProfile
from job_agent.utils.cv import extract_cv_text
from job_agent.utils.llm import call_llm
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "profiler.md"

_PROFILE_KEYS = {
    "name",
    "headline",
    "email",
    "phone",
    "location",
    "languages",
    "skills",
    "experience",
    "education",
    "preferences",
}


def profile_from_cv_file(path: str | Path) -> UserProfile:
    """Read a CV file and extract a structured profile (convenience wrapper)."""
    return run_profiler(extract_cv_text(path))


def run_profiler(cv_text: str) -> UserProfile:
    """Extract a structured :class:`UserProfile` from raw CV text via the LLM."""
    if not cv_text.strip():
        raise ValueError("CV text is empty — nothing to profile.")

    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    log.info("[profiler] extracting profile from %d chars of CV text", len(cv_text))
    raw = call_llm(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"CV text:\n\n{cv_text.strip()}"},
        ]
    )
    data = _parse_json_object(raw)
    profile = UserProfile.model_validate(_coerce_profile_dict(data))
    log.info(
        "[profiler] built profile for %s — %d skills, %d experiences",
        profile.name,
        len(profile.skills),
        len(profile.experience),
    )
    return profile


def _parse_json_object(raw: str) -> dict[str, Any]:
    """Parse the LLM reply into a dict, tolerating fences and stray prose."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"Profiler returned no JSON object:\n{raw[:500]}") from None
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Profiler output was not a JSON object")
    return data


def _coerce_profile_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Filter to known keys, normalize skills, and backfill required fields.

    UserProfile uses ``extra = "forbid"``, so unknown keys from the LLM would
    otherwise raise. We also harden against minor omissions in the LLM output.
    """
    out: dict[str, Any] = {k: v for k, v in data.items() if k in _PROFILE_KEYS}

    raw_skills = out.get("skills")
    if isinstance(raw_skills, list):
        seen: set[str] = set()
        skills: list[str] = []
        for item in raw_skills:
            token = str(item).strip().lower()
            if token and token not in seen:
                seen.add(token)
                skills.append(token)
        out["skills"] = skills
    else:
        out["skills"] = []

    if not isinstance(out.get("languages"), dict):
        out["languages"] = {}

    out.setdefault("name", "Unknown Candidate")
    out.setdefault("email", "")
    out.setdefault("location", "")
    if not out.get("headline"):
        out["headline"] = _derive_headline(out)
    return out


def _derive_headline(out: dict[str, Any]) -> str:
    experience = out.get("experience")
    if isinstance(experience, list) and experience and isinstance(experience[0], dict):
        role = str(experience[0].get("role", "")).strip()
        if role:
            return role
    education = out.get("education")
    if isinstance(education, list) and education and isinstance(education[0], dict):
        degree = str(education[0].get("degree", "")).strip()
        field = str(education[0].get("field", "")).strip()
        tagline = " ".join(part for part in (degree, field) if part)
        if tagline:
            return tagline
    return str(out.get("name", "Candidate"))
