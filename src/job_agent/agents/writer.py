"""Writer agent — drafts a tailored German cover letter.

Sprint 3 adds an optional LLM writer. The template writer remains as a
fallback so demos do not fail when the configured LLM is unavailable.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from job_agent.schemas import GeneratedApplication, JobPosting, MatchResult, UserProfile
from job_agent.utils.config import settings
from job_agent.utils.llm import call_llm
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "writer.md"


_TEMPLATE = """\
**Bewerbung: {title} - {company}**

{greeting},

mit großem Interesse habe ich Ihre Stellenausschreibung als **{title}**
gelesen. Besonders relevant finde ich: {job_hook}

Als {headline} aus {location} bringe ich folgende von Ihnen gewünschte
Qualifikationen mit: {matched_skills}. In meinen bisherigen Projekten habe
ich vergleichbare Aufgaben strukturiert umgesetzt und Ergebnisse sauber
dokumentiert.

{rationale}

Über die Möglichkeit, mich in einem persönlichen Gespräch vorzustellen,
würde ich mich sehr freuen.

Mit freundlichen Grüßen
{name}
"""


def run_writer(
    job: JobPosting,
    match: MatchResult,
    profile: UserProfile,
    use_llm: bool | None = None,
    profile_context: list[str] | None = None,
) -> GeneratedApplication:
    """Produce a tailored application for one (job, match) pair."""
    llm_enabled = settings.enable_llm_agents if use_llm is None else use_llm
    if llm_enabled:
        try:
            app = _run_llm_writer(job, match, profile, profile_context)
            log.info("[writer:llm] drafted application for %s", job.id)
            return app
        except Exception as exc:
            log.warning("[writer:llm] falling back for %s: %s", job.id, exc)

    app = _run_template_writer(job, match, profile)
    log.info("[writer] drafted application for %s (checks=%s)", job.id, app.quality_checks)
    return app


def _run_template_writer(
    job: JobPosting,
    match: MatchResult,
    profile: UserProfile,
) -> GeneratedApplication:
    matched_str = ", ".join(match.matched_skills) if match.matched_skills else "-"
    letter = _TEMPLATE.format(
        title=job.title,
        company=job.company,
        greeting=_greeting(job.description),
        job_hook=_job_hook(job),
        headline=profile.headline,
        location=profile.location,
        matched_skills=matched_str,
        rationale=match.rationale,
        name=profile.name,
    )

    return GeneratedApplication(
        job_id=job.id,
        cover_letter_md=letter,
        tailored_cv_path=None,
        generated_at=date.today(),
        quality_checks=_quality_checks(letter, job, profile),
    )


def _run_llm_writer(
    job: JobPosting,
    match: MatchResult,
    profile: UserProfile,
    profile_context: list[str] | None,
) -> GeneratedApplication:
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    user_payload = {
        "job": job.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "match": match.model_dump(mode="json"),
        "profile_context": profile_context or [],
        "today": date.today().isoformat(),
    }
    raw = call_llm(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Return only one JSON object matching GeneratedApplication.\n"
                    f"{json.dumps(user_payload, ensure_ascii=False)}"
                ),
            },
        ]
    )
    app = _parse_application(raw, expected_job_id=job.id)
    app.quality_checks = _quality_checks(app.cover_letter_md, job, profile)
    return app


def _parse_application(raw: Any, expected_job_id: str) -> GeneratedApplication:
    if isinstance(raw, GeneratedApplication):
        return raw
    if not isinstance(raw, str):
        raise TypeError(f"expected string LLM output, got {type(raw)!r}")
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM writer output was not a JSON object")
    data["job_id"] = data.get("job_id") or expected_job_id
    data.setdefault("tailored_cv_path", None)
    data.setdefault("generated_at", date.today().isoformat())
    data.setdefault("quality_checks", {})
    return GeneratedApplication.model_validate(data)


def _greeting(description: str) -> str:
    """Use a named contact from the posting if the description exposes one."""
    patterns = [
        r"(?:ansprechpartner(?:in)?|kontakt)\s*[:\-]\s*(?P<name>(?:frau|herr)\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+){0,2})",
        r"(?P<name>(?:Frau|Herr)\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+){0,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, description, flags=re.IGNORECASE)
        if not match:
            continue
        name = match.group("name").strip()
        if name.lower().startswith("frau"):
            return f"Sehr geehrte {name}"
        return f"Sehr geehrter {name}"
    return "Sehr geehrte Damen und Herren"


def _job_hook(job: JobPosting) -> str:
    details: list[str] = []
    if job.requirements:
        details.append("die Arbeit mit " + ", ".join(job.requirements[:4]))
    first_sentence = _first_sentence(job.description)
    if first_sentence:
        details.append(first_sentence)
    return "; ".join(details[:2]) if details else f"die Aufgaben im Bereich {job.title}"


def _first_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    return cleaned.split(".", 1)[0].strip()[:220]


def _quality_checks(
    letter: str,
    job: JobPosting,
    profile: UserProfile,
) -> dict[str, bool]:
    return {
        "name_correct": profile.name.lower() in letter.lower(),
        "no_placeholders": "{{" not in letter and "}}" not in letter,
        "length_ok": 200 <= len(letter) <= 4000,
        "mentions_job_title": job.title.lower() in letter.lower(),
        "no_sprint_note": "Sprint-1 template draft" not in letter,
    }
