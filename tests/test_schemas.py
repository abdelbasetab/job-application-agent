"""Schema-level tests — these guard every contract between agents."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
    MatchResult,
    ScoreComponent,
    UserProfile,
)
from job_agent.schemas.profile import Experience, Preferences


def _job(**overrides) -> JobPosting:
    defaults = dict(
        id="t-1",
        source="manual",
        source_id="t-1",
        url="https://example.com/t-1",
        title="Test Role",
        company="Acme",
        location="Berlin",
        description="A job.",
        requirements=["python"],
    )
    defaults.update(overrides)
    return JobPosting(**defaults)


def test_jobposting_minimal_valid() -> None:
    job = _job()
    assert job.id == "t-1"
    assert job.requirements == ["python"]


def test_jobposting_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        JobPosting(  # type: ignore[call-arg]
            id="t-1",
            source="manual",
            source_id="t-1",
            url="https://example.com/t-1",
            title="x",
            company="x",
            location="x",
            description="x",
            invented_field="not allowed",
        )


def test_jobposting_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        _job(source="some-random-board")


def test_matchresult_score_bounds() -> None:
    with pytest.raises(ValidationError):
        MatchResult(job_id="x", score=1.5, rationale="r")
    with pytest.raises(ValidationError):
        MatchResult(job_id="x", score=-0.1, rationale="r")


def test_matchresult_accepts_explainable_rubric() -> None:
    match = MatchResult(
        job_id="x",
        score=0.82,
        rationale="Strong fit.",
        score_components=[
            ScoreComponent(
                key="hard_skills",
                label="Muss-Skills",
                score=4,
                weight=45,
                evidence="2/3 skills match.",
            )
        ],
        risk_level="low",
        recommendation="strong",
        score_summary="Sehr guter Fit.",
    )

    assert match.score_components[0].score == 4
    assert match.risk_level == "low"


def test_userprofile_round_trip() -> None:
    profile = UserProfile(
        name="A",
        headline="h",
        email="a@b.de",
        location="Berlin",
        languages={"de": "C1"},
        skills=["python"],
        experience=[Experience(role="r", company="c", start="2024-01")],
        preferences=Preferences(locations=["Berlin"]),
    )
    blob = profile.model_dump_json()
    again = UserProfile.model_validate_json(blob)
    assert again == profile


def test_applicationstatus_default_stage() -> None:
    s = ApplicationStatus(job_id="t-1")
    assert s.status == "draft"


def test_generated_application_quality_flags() -> None:
    app = GeneratedApplication(
        job_id="t-1",
        cover_letter_md="Sehr geehrte Damen und Herren …",
        generated_at=date.today(),
        quality_checks={"name_correct": True},
    )
    assert app.quality_checks["name_correct"] is True
