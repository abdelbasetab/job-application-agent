"""CV Reviewer agent — bewertet die Qualität des Lebenslaufs selbst.

Der Matcher bewertet *Job vs. Profil*; dieser Agent bewertet das Dokument:
Ist der Lebenslauf vollständig, strukturiert, konkret und angemessen lang?
Das Ergebnis ist eine erklärbare 1-5-Rubrik (wie beim Matcher) plus konkrete
deutsche Verbesserungstipps.

Die Rubrik ist vollständig deterministisch und offline. Optional ergänzt der
konfigurierte LLM einen Freitext-Absatz (``llm_feedback``); fällt der Aufruf
aus, bleibt das Feld leer — die Bewertung funktioniert trotzdem.
"""

from __future__ import annotations

import re
from pathlib import Path

from job_agent.schemas import CVAssessment, ScoreComponent, UserProfile
from job_agent.utils.config import settings
from job_agent.utils.llm import call_llm
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "cv_reviewer.md"

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s/().-]{7,}\d)")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|prozent|jahre?|monate|stunden|projekte?|€|eur)\b", re.IGNORECASE)

_SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "experience": ("berufserfahrung", "praxiserfahrung", "erfahrung", "experience", "werdegang"),
    "education": ("ausbildung", "studium", "education", "bildungsweg", "hochschule"),
    "skills": ("kenntnisse", "skills", "fähigkeiten", "kompetenzen", "technologien"),
    "projects": ("projekte", "projects", "portfolio"),
}

_LANGUAGE_LEVEL_TERMS = (
    "a1", "a2", "b1", "b2", "c1", "c2",
    "fließend", "verhandlungssicher", "muttersprache", "native", "fluent",
)
_LANGUAGE_SECTION_TERMS = ("sprachen", "sprachkenntnisse", "languages")

_ACTION_VERBS = (
    "entwickelt", "aufgebaut", "implementiert", "optimiert", "automatisiert",
    "konzipiert", "verantwortet", "analysiert", "migriert", "eingeführt",
    "developed", "built", "implemented", "automated", "designed", "led",
)

_TECH_KEYWORDS = (
    "python", "java", "c++", "c#", "javascript", "typescript", "sql", "git",
    "docker", "kubernetes", "linux", "aws", "azure", "react", "node", "html",
    "css", "pandas", "numpy", "excel", "matlab", "llm", "rag", "chromadb",
    "machine learning", "deep learning", "crewai", "pytorch", "tensorflow",
)


def run_cv_reviewer(
    cv_text: str,
    profile: UserProfile | None = None,
    use_llm: bool | None = None,
) -> CVAssessment:
    """Bewerte einen Lebenslauf-Text; optional mit strukturiertem Profil als Kontext."""
    text = cv_text.strip()
    if not text:
        raise ValueError("CV text is empty — nothing to review.")
    lowered = text.lower()
    words = len(text.split())

    components = [
        _contact_component(lowered, profile),
        _structure_component(lowered),
        _skills_component(lowered, profile),
        _impact_component(lowered),
        _language_component(lowered, profile),
        _length_component(words),
    ]
    overall = _weighted_overall(components)
    tips = _tips(components)
    summary = _summary(overall, components)

    llm_feedback = ""
    llm_enabled = settings.enable_llm_agents if use_llm is None else use_llm
    if llm_enabled:
        llm_feedback = _llm_feedback(text, components, overall)

    assessment = CVAssessment(
        overall_score=overall,
        components=components,
        tips=tips,
        summary=summary,
        word_count=words,
        llm_feedback=llm_feedback,
    )
    log.info("[cv-review] %d Wörter -> %.1f/5 (%d Tipps)", words, overall, len(tips))
    return assessment


def _contact_component(lowered: str, profile: UserProfile | None) -> ScoreComponent:
    has_email = bool(_EMAIL_RE.search(lowered)) or bool(profile and profile.email)
    has_phone = bool(_PHONE_RE.search(lowered)) or bool(profile and profile.phone)
    if has_email and has_phone:
        score, evidence = 5, "E-Mail und Telefonnummer gefunden."
    elif has_email:
        score, evidence = 3, "E-Mail gefunden, aber keine Telefonnummer."
    elif has_phone:
        score, evidence = 2, "Telefonnummer gefunden, aber keine E-Mail-Adresse."
    else:
        score, evidence = 1, "Keine Kontaktdaten (E-Mail/Telefon) erkennbar."
    return ScoreComponent(
        key="kontakt", label="Kontaktdaten", score=score, weight=20, evidence=evidence
    )


def _structure_component(lowered: str) -> ScoreComponent:
    found = [
        name
        for name, keywords in _SECTION_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    score = {4: 5, 3: 4, 2: 3, 1: 2}.get(len(found), 1)
    labels = {
        "experience": "Erfahrung",
        "education": "Ausbildung",
        "skills": "Skills",
        "projects": "Projekte",
    }
    if found:
        evidence = "Erkannte Abschnitte: " + ", ".join(labels[name] for name in found) + "."
    else:
        evidence = "Keine klaren Abschnitte (Erfahrung/Ausbildung/Skills) erkennbar."
    return ScoreComponent(
        key="struktur", label="Struktur", score=score, weight=20, evidence=evidence
    )


def _skills_component(lowered: str, profile: UserProfile | None) -> ScoreComponent:
    if profile is not None and profile.skills:
        count = len(profile.skills)
        source = "aus dem strukturierten Profil"
    else:
        count = sum(1 for keyword in _TECH_KEYWORDS if keyword in lowered)
        source = "per Stichwort-Erkennung"
    if count >= 8:
        score = 5
    elif count >= 5:
        score = 4
    elif count >= 3:
        score = 3
    elif count >= 1:
        score = 2
    else:
        score = 1
    return ScoreComponent(
        key="skills",
        label="Skills",
        score=score,
        weight=20,
        evidence=f"{count} technische Skills erkannt ({source}).",
    )


def _impact_component(lowered: str) -> ScoreComponent:
    numbers = len(_NUMBER_RE.findall(lowered))
    verbs = sum(1 for verb in _ACTION_VERBS if verb in lowered)
    signals = numbers + verbs
    if signals >= 6:
        score = 5
    elif signals >= 4:
        score = 4
    elif signals >= 2:
        score = 3
    elif signals >= 1:
        score = 2
    else:
        score = 1
    return ScoreComponent(
        key="konkretheit",
        label="Konkretheit",
        score=score,
        weight=15,
        evidence=(
            f"{verbs} aktive Verben und {numbers} Zahlen/Messgrößen gefunden — "
            "konkrete Ergebnisse überzeugen Recruiter."
        ),
    )


def _language_component(lowered: str, profile: UserProfile | None) -> ScoreComponent:
    if profile is not None and profile.languages:
        levels = ", ".join(f"{code}: {level}" for code, level in profile.languages.items())
        return ScoreComponent(
            key="sprachen",
            label="Sprachen",
            score=5,
            weight=10,
            evidence=f"Sprachen mit Niveau angegeben ({levels}).",
        )
    has_section = any(term in lowered for term in _LANGUAGE_SECTION_TERMS)
    has_level = any(term in lowered for term in _LANGUAGE_LEVEL_TERMS)
    if has_section and has_level:
        score, evidence = 5, "Sprachen inklusive Niveau (z.B. C1) angegeben."
    elif has_section:
        score, evidence = 4, "Sprachabschnitt vorhanden, aber ohne Niveauangabe."
    else:
        score, evidence = 2, "Keine Sprachkenntnisse angegeben."
    return ScoreComponent(
        key="sprachen", label="Sprachen", score=score, weight=10, evidence=evidence
    )


def _length_component(words: int) -> ScoreComponent:
    if 250 <= words <= 800:
        score, evidence = 5, f"{words} Wörter — angemessener Umfang."
    elif 150 <= words < 250 or 800 < words <= 1100:
        score, evidence = 4, f"{words} Wörter — noch im Rahmen."
    elif 100 <= words < 150 or 1100 < words <= 1500:
        score, evidence = 3, f"{words} Wörter — etwas zu knapp bzw. zu lang."
    elif 50 <= words < 100:
        score, evidence = 2, f"Nur {words} Wörter — zu wenig Substanz."
    else:
        score, evidence = 1, f"{words} Wörter — deutlich außerhalb des sinnvollen Rahmens."
    return ScoreComponent(
        key="umfang", label="Umfang", score=score, weight=15, evidence=evidence
    )


def _weighted_overall(components: list[ScoreComponent]) -> float:
    total = sum(component.weight for component in components)
    if not total:
        return 1.0
    raw = sum(component.score * component.weight for component in components) / total
    return round(min(5.0, max(1.0, raw)), 1)


_TIP_BY_KEY = {
    "kontakt": "Ergänze vollständige Kontaktdaten (E-Mail und Telefonnummer) im Kopfbereich.",
    "struktur": (
        "Gliedere den Lebenslauf in klare Abschnitte: Berufserfahrung, Ausbildung, "
        "Skills, Projekte."
    ),
    "skills": (
        "Liste deine technischen Skills explizit auf (z.B. Python, SQL, Git) — "
        "ATS-Systeme und Recruiter suchen danach."
    ),
    "konkretheit": (
        "Formuliere Erfahrungen aktiv und messbar: „Pipeline entwickelt, "
        "Laufzeit um 30% reduziert“ statt „zuständig für…“."
    ),
    "sprachen": "Gib Sprachkenntnisse mit Niveau an (z.B. Deutsch C1, Englisch B2).",
    "umfang": "Ziel sind 1-2 Seiten (ca. 250-800 Wörter): kürze Fülltext oder ergänze Substanz.",
}


def _tips(components: list[ScoreComponent]) -> list[str]:
    weak = sorted(
        (c for c in components if c.score <= 3),
        key=lambda c: (c.score, -c.weight),
    )
    return [_TIP_BY_KEY[c.key] for c in weak if c.key in _TIP_BY_KEY][:5]


def _summary(overall: float, components: list[ScoreComponent]) -> str:
    if overall >= 4.5:
        band = "Sehr überzeugender Lebenslauf"
    elif overall >= 3.5:
        band = "Solider Lebenslauf"
    elif overall >= 2.5:
        band = "Ausbaufähiger Lebenslauf"
    else:
        band = "Deutlich verbesserungswürdiger Lebenslauf"
    best = max(components, key=lambda c: (c.score, c.weight))
    worst = min(components, key=lambda c: (c.score, -c.weight))
    return f"{band} ({overall:.1f}/5). Stärke: {best.label}. Größter Hebel: {worst.label}."


def _llm_feedback(text: str, components: list[ScoreComponent], overall: float) -> str:
    """Ein kurzer Freitext-Absatz vom LLM — best effort, niemals blockierend."""
    try:
        prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        rubric = "\n".join(
            f"- {c.label}: {c.score}/5 ({c.evidence})" for c in components
        )
        raw = call_llm(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Deterministische Rubrik ({overall:.1f}/5):\n{rubric}\n\n"
                        f"Lebenslauf:\n{text[:6000]}"
                    ),
                },
            ]
        )
        return raw.strip()[:1500]
    except Exception as exc:
        log.warning("[cv-review] LLM feedback unavailable: %s", exc)
        return ""
