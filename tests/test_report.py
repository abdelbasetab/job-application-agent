"""Offline tests for the Markdown evaluation report."""

from __future__ import annotations

from datetime import datetime

from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
    LivenessResult,
    MatchResult,
    ScoreComponent,
)
from job_agent.tools.report import REPORT_FILENAME, evaluation_report_md


def _job() -> JobPosting:
    return JobPosting(
        id="rep-1",
        source="manual",
        source_id="rep-1",
        url="https://example.de/jobs/rep-1",
        title="Werkstudent KI",
        company="RuhrTech GmbH",
        location="Gelsenkirchen",
        description="Du baust LLM-Prototypen. " * 20,
        requirements=["python", "llms"],
        salary_range=(20000, 24000),
        remote=True,
    )


def _match() -> MatchResult:
    return MatchResult(
        job_id="rep-1",
        score=0.92,
        matched_skills=["python", "llms"],
        missing_skills=["docker"],
        rationale="2/2 Muss-Skills passen.",
        score_components=[
            ScoreComponent(
                key="hard_skills",
                label="Muss-Skills",
                score=5,
                weight=45,
                evidence="2/2 Muss-Skills erkannt: python, llms.",
            )
        ],
        risk_level="low",
        risk_flags=[],
        recommendation="strong",
        score_summary="Sehr guter Fit.",
    )


def test_report_contains_all_sections() -> None:
    md = evaluation_report_md(
        _job(),
        match=_match(),
        application=GeneratedApplication(
            job_id="rep-1",
            cover_letter_md="Sehr geehrte Damen und Herren, ...",
            quality_checks={"name_correct": True, "length_ok": False},
        ),
        status=ApplicationStatus(
            job_id="rep-1",
            status="submitted",
            submitted_at=datetime(2026, 7, 1, 9, 0),
            updated_at=datetime(2026, 7, 5, 10, 0),
            notes="E-Mail gesendet an hr@ruhrtech.de.",
        ),
        status_events=[
            {
                "created_at": "2026-07-01T10:30:00",
                "previous_status": "draft",
                "new_status": "submitted",
                "event_type": "manual_update",
            }
        ],
        liveness=LivenessResult(
            url="https://example.de/jobs/rep-1",
            status="live",
            confidence=0.9,
            reason="HTTP 200, Titel gefunden.",
        ),
    )

    assert md.startswith("# Bewertungsreport: Werkstudent KI")
    assert "**Score:** 0.92 (92%)" in md
    assert "| Muss-Skills | 5/5 | 45 % |" in md
    assert "Sehr guter Fit — bewerben" in md
    assert "Ghost-Job- / Scam-Check" in md
    assert "Keine starken Ghost-Job- oder Scam-Signale" in md
    assert "✓ name_correct" in md and "✗ length_ok" in md
    assert "Sehr geehrte Damen und Herren" in md
    assert "E-Mail gesendet an hr@ruhrtech.de." in md
    assert "### Statusverlauf" in md
    assert "draft → submitted" in md
    assert "offen (90%)" in md
    assert "20.000 - 24.000 EUR" in md
    assert REPORT_FILENAME.endswith(".md")


def test_report_without_match_is_honest() -> None:
    md = evaluation_report_md(_job())
    assert "Noch keine Bewertung vorhanden" in md
    assert "Ghost-Job" not in md.split("## Anzeige")[0].split("## Bewertung")[1]
