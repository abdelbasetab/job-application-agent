"""Offline tests for the interview preparation guide."""

from __future__ import annotations

from job_agent.agents.interview_prep import build_interview_prep, interview_prep_md
from job_agent.schemas import JobPosting, MatchResult, UserProfile
from job_agent.schemas.profile import Preferences


def _job() -> JobPosting:
    return JobPosting(
        id="ip-1",
        source="manual",
        source_id="ip-1",
        url="https://example.de/jobs/ip-1",
        title="Werkstudent KI",
        company="RuhrTech GmbH",
        location="Gelsenkirchen",
        description="LLM-Prototypen mit Python und RAG bauen und evaluieren.",
        requirements=["python", "rag", "docker"],
    )


def _profile() -> UserProfile:
    return UserProfile(
        name="Test Candidate",
        headline="AI Engineering Student",
        email="test@example.com",
        location="Gelsenkirchen",
        languages={"de": "C1"},
        skills=["python", "rag", "sql"],
        preferences=Preferences(locations=["Gelsenkirchen"]),
    )


def _match() -> MatchResult:
    return MatchResult(
        job_id="ip-1",
        score=0.8,
        matched_skills=["python", "rag"],
        missing_skills=["docker"],
        rationale="stub",
    )


def test_guide_uses_matched_and_missing_skills() -> None:
    guide = build_interview_prep(_job(), _profile(), match=_match(), use_llm=False)

    skills = [item["skill"] for item in guide["fachfragen"]]
    assert skills == ["python", "rag"]
    gaps = [item["skill"] for item in guide["lueckenfragen"]]
    assert gaps == ["docker"]
    assert any("ehrlich" in item["tipp"].lower() for item in guide["lueckenfragen"])
    assert guide["llm_fragen"] == []
    assert "RuhrTech GmbH" in guide["unternehmensfragen"][0]
    assert len(guide["rueckfragen"]) >= 3


def test_guide_without_match_falls_back_to_profile() -> None:
    guide = build_interview_prep(_job(), _profile(), match=None, use_llm=False)
    skills = [item["skill"] for item in guide["fachfragen"]]
    assert skills, "auch ohne Match gibt es Fachfragen"
    assert set(skills) <= set(_profile().skills)


def test_markdown_rendering_has_sections() -> None:
    md = interview_prep_md(build_interview_prep(_job(), _profile(), match=_match(), use_llm=False))
    assert md.startswith("# Interview-Vorbereitung: Werkstudent KI")
    assert "## Fachfragen" in md
    assert "## Lücken souverän beantworten" in md
    assert "## Deine Rückfragen" in md


def test_llm_questions_are_best_effort(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "job_agent.agents.interview_prep.call_llm",
        lambda messages, **_kw: "Wie skalierst du RAG-Retrieval?\nWas war dein schwierigster Bug?\nWie misst du Antwortqualität?",
    )
    guide = build_interview_prep(_job(), _profile(), match=_match(), use_llm=True)
    assert len(guide["llm_fragen"]) == 3

    def broken(messages, **_kw):  # type: ignore[no-untyped-def]
        raise RuntimeError("kein Provider")

    monkeypatch.setattr("job_agent.agents.interview_prep.call_llm", broken)
    guide = build_interview_prep(_job(), _profile(), match=_match(), use_llm=True)
    assert guide["llm_fragen"] == []
