"""Interview-Vorbereitung light (career-ops: „interview-prep", Block F).

Erzeugt pro Stelle einen kompakten Vorbereitungs-Leitfaden: wahrscheinliche
Fachfragen zu den passenden Skills (STAR-tauglich formuliert), ehrliche
Strategien für fehlende Skills, allgemeine Verhaltensfragen und gute
Rückfragen an das Unternehmen.

Der Kern ist deterministisch und offline; ``use_llm`` ergänzt optional 2-3
anzeigenspezifische Fragen über das konfigurierte LLM (best effort, niemals
blockierend).
"""

from __future__ import annotations

from typing import Any

from job_agent.schemas import JobPosting, MatchResult, UserProfile
from job_agent.utils.config import settings
from job_agent.utils.llm import call_llm
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

_STAR_HINT = (
    "Antworte nach STAR: Situation, Task (Aufgabe), Action (dein Beitrag), "
    "Result (messbares Ergebnis) — 90 Sekunden pro Antwort."
)

_BEHAVIORAL_QUESTIONS = (
    "Erzählen Sie von einem Projekt, auf das Sie stolz sind — was war Ihr konkreter Anteil?",
    "Beschreiben Sie eine Situation, in der etwas schiefging. Wie sind Sie damit umgegangen?",
    "Wie organisieren Sie sich, wenn Studium und Job parallel laufen?",
)

_CANDIDATE_QUESTIONS = (
    "Wie sieht eine typische Woche in dieser Rolle aus?",
    "Woran würden Sie nach drei Monaten festmachen, dass die Einarbeitung gelungen ist?",
    "Wie arbeitet das Team: Code-Reviews, Pairing, Daily?",
    "Welche Entwicklungsmöglichkeiten gibt es nach der Werkstudententätigkeit?",
)


def build_interview_prep(
    job: JobPosting,
    profile: UserProfile,
    match: MatchResult | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """Assemble the per-job interview guide as a JSON-serializable dict."""
    matched = list(match.matched_skills) if match else []
    missing = list(match.missing_skills) if match else []
    if not matched and profile.skills:
        # Without a match we still prepare on the profile's strongest skills.
        matched = [
            skill for skill in profile.skills if skill in {r.lower() for r in job.requirements}
        ] or profile.skills[:3]

    skill_questions = [
        {
            "skill": skill,
            "frage": (
                f"Erzählen Sie von einem Projekt, in dem Sie {skill} eingesetzt haben — "
                "was war Ihr Beitrag, was das Ergebnis?"
            ),
            "tipp": _STAR_HINT if index == 0 else "Konkretes Projekt + Zahl schlägt Aufzählung.",
        }
        for index, skill in enumerate(matched[:5])
    ]
    gap_questions = [
        {
            "skill": skill,
            "frage": f"Mit {skill} haben Sie noch wenig gearbeitet — wie würden Sie sich das erarbeiten?",
            "tipp": (
                "Ehrlich bleiben, Lernweg skizzieren (verwandte Erfahrung, konkretes "
                "Lernprojekt) — nichts vortäuschen."
            ),
        }
        for skill in missing[:3]
    ]

    company_questions = [
        f"Warum {job.company} — und warum gerade die Rolle „{job.title}“?",
        "Was wissen Sie über unsere Produkte/Projekte?",
    ]

    guide: dict[str, Any] = {
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "star_hinweis": _STAR_HINT,
        "fachfragen": skill_questions,
        "lueckenfragen": gap_questions,
        "unternehmensfragen": company_questions,
        "verhaltensfragen": list(_BEHAVIORAL_QUESTIONS),
        "rueckfragen": list(_CANDIDATE_QUESTIONS),
        "llm_fragen": [],
    }

    llm_enabled = settings.enable_llm_agents if use_llm is None else use_llm
    if llm_enabled:
        guide["llm_fragen"] = _llm_questions(job)

    log.info(
        "[interview-prep] %s: %d Fach-, %d Lücken-, %d LLM-Fragen",
        job.id,
        len(skill_questions),
        len(gap_questions),
        len(guide["llm_fragen"]),
    )
    return guide


def _llm_questions(job: JobPosting) -> list[str]:
    """2-3 anzeigenspezifische Fragen vom LLM — best effort, nie blockierend."""
    try:
        raw = call_llm(
            [
                {
                    "role": "system",
                    "content": (
                        "Du bist Interviewer. Formuliere genau 3 spezifische, faire "
                        "Interviewfragen auf Deutsch zu dieser Stellenanzeige. "
                        "Eine Frage pro Zeile, keine Nummerierung, kein Markdown."
                    ),
                },
                {"role": "user", "content": f"{job.title} bei {job.company}:\n{job.description[:3000]}"},
            ]
        )
        questions = [line.strip("-• ").strip() for line in raw.splitlines() if line.strip()]
        return [q for q in questions if len(q) > 15][:3]
    except Exception as exc:
        log.warning("[interview-prep] LLM-Fragen nicht verfügbar: %s", exc)
        return []


def interview_prep_md(guide: dict[str, Any]) -> str:
    """Render the guide as Markdown (CLI output / export)."""
    lines: list[str] = [f"# Interview-Vorbereitung: {guide['title']} — {guide['company']}", ""]
    lines += [f"> {guide['star_hinweis']}", ""]
    if guide["fachfragen"]:
        lines += ["## Fachfragen (deine Stärken)", ""]
        for item in guide["fachfragen"]:
            lines.append(f"- **{item['skill']}**: {item['frage']}")
            lines.append(f"  - Tipp: {item['tipp']}")
        lines.append("")
    if guide["lueckenfragen"]:
        lines += ["## Lücken souverän beantworten", ""]
        for item in guide["lueckenfragen"]:
            lines.append(f"- **{item['skill']}**: {item['frage']}")
            lines.append(f"  - Tipp: {item['tipp']}")
        lines.append("")
    lines += ["## Unternehmen & Motivation", ""]
    lines += [f"- {question}" for question in guide["unternehmensfragen"]]
    lines += ["", "## Verhaltensfragen", ""]
    lines += [f"- {question}" for question in guide["verhaltensfragen"]]
    if guide.get("llm_fragen"):
        lines += ["", "## Anzeigenspezifisch (LLM)", ""]
        lines += [f"- {question}" for question in guide["llm_fragen"]]
    lines += ["", "## Deine Rückfragen", ""]
    lines += [f"- {question}" for question in guide["rueckfragen"]]
    lines.append("")
    return "\n".join(lines)
