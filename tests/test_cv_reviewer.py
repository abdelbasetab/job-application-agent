"""Offline tests for the CV Reviewer agent (Lebenslauf-Bewertung)."""

from __future__ import annotations

import pytest

from job_agent.agents.cv_reviewer import run_cv_reviewer
from job_agent.demo_profile import demo_profile

_STRONG_CV = """
Abdel Beispiel
E-Mail: abdel@example.com — Telefon: +49 176 1234567 — Gelsenkirchen

Berufserfahrung
Werkstudent Datenanalyse, Beispiel GmbH (2024-2025)
- ETL-Pipeline mit Python und SQL entwickelt, Laufzeit um 30 % reduziert
- Reporting mit Pandas automatisiert, 4 Stunden pro Woche eingespart
- Docker-Setup für das Team implementiert und dokumentiert

Projekte
- RAG-Prototyp mit LLM und ChromaDB aufgebaut (Studienprojekt, 2 Jahre Git-Historie)
- Linux-Homeserver konzipiert und optimiert

Studium
B.Sc. Informatik, Westfälische Hochschule, seit 2023

Kenntnisse
Python, SQL, Git, Docker, Linux, Pandas, LLM, RAG, Machine Learning

Sprachen
Deutsch C1, Englisch B2, Arabisch Muttersprache
"""

_WEAK_CV = "Ich suche einen Nebenjob. Ich bin motiviert und lerne schnell."


def test_strong_cv_scores_high_with_few_tips() -> None:
    assessment = run_cv_reviewer(_STRONG_CV, use_llm=False)

    assert assessment.overall_score >= 4.0
    assert assessment.word_count > 80
    assert len(assessment.tips) <= 2
    assert {c.key for c in assessment.components} == {
        "kontakt",
        "struktur",
        "skills",
        "konkretheit",
        "sprachen",
        "umfang",
    }
    kontakt = next(c for c in assessment.components if c.key == "kontakt")
    assert kontakt.score == 5, "email + phone must be detected"


def test_weak_cv_scores_low_with_actionable_tips() -> None:
    assessment = run_cv_reviewer(_WEAK_CV, use_llm=False)

    assert assessment.overall_score <= 2.5
    assert len(assessment.tips) >= 3
    assert any("Kontaktdaten" in tip for tip in assessment.tips)
    assert assessment.summary  # UI one-liner must always exist


def test_strong_cv_outranks_weak_cv() -> None:
    strong = run_cv_reviewer(_STRONG_CV, use_llm=False)
    weak = run_cv_reviewer(_WEAK_CV, use_llm=False)
    assert strong.overall_score > weak.overall_score


def test_structured_profile_feeds_skills_and_languages() -> None:
    assessment = run_cv_reviewer(_WEAK_CV, profile=demo_profile(), use_llm=False)

    skills = next(c for c in assessment.components if c.key == "skills")
    assert skills.score >= 4, "7 profile skills must outweigh the empty text"
    sprachen = next(c for c in assessment.components if c.key == "sprachen")
    assert sprachen.score == 5


def test_empty_cv_raises() -> None:
    with pytest.raises(ValueError):
        run_cv_reviewer("   ", use_llm=False)


def test_llm_feedback_is_best_effort(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def broken_llm(messages):
        raise RuntimeError("no provider")

    monkeypatch.setattr("job_agent.agents.cv_reviewer.call_llm", broken_llm)
    assessment = run_cv_reviewer(_STRONG_CV, use_llm=True)
    assert assessment.llm_feedback == ""  # failure must not break the review

    monkeypatch.setattr(
        "job_agent.agents.cv_reviewer.call_llm",
        lambda messages: "Dein größter Hebel ist mehr Wirkung in den Projekten.",
    )
    assessment = run_cv_reviewer(_STRONG_CV, use_llm=True)
    assert "Hebel" in assessment.llm_feedback
