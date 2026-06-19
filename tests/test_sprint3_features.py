from __future__ import annotations

from pathlib import Path

from job_agent.agents.matcher import run_matcher
from job_agent.agents.writer import run_writer
from job_agent.memory.profile_index import ProfileVectorStore
from job_agent.schemas import JobPosting, MatchResult, UserProfile
from job_agent.schemas.profile import Experience, Preferences
from job_agent.tools.job_search import parse_salary_range


def _profile() -> UserProfile:
    return UserProfile(
        name="Test Candidate",
        headline="AI Engineering Student",
        email="test@example.com",
        location="Gelsenkirchen",
        languages={"de": "C1", "en": "C1"},
        skills=["python", "sql", "rag", "llms"],
        experience=[
            Experience(
                role="AI Coursework",
                company="Westfaelische Hochschule",
                start="2025-10",
                summary="Built RAG and LLM prototypes with Python.",
                skills_used=["python", "rag", "llms"],
            )
        ],
        preferences=Preferences(locations=["Gelsenkirchen", "Essen", "Remote"]),
    )


def _job() -> JobPosting:
    return JobPosting(
        id="job-1",
        source="manual",
        source_id="job-1",
        url="https://example.com/job-1",
        title="Werkstudent KI Automation",
        company="Example GmbH",
        location="Essen",
        description="LLM and RAG automation with Python.",
        requirements=["python", "rag"],
        nice_to_have=["sql"],
        salary_range=(50000, 70000),
    )


def test_parse_salary_range_german_formats() -> None:
    assert parse_salary_range("Gehalt: 50.000 - 70.000 EUR") == (50000, 70000)
    assert parse_salary_range("zwischen 70000 und 50000 Euro") is None
    assert parse_salary_range("60 000 bis 80 000 €") == (60000, 80000)
    assert parse_salary_range("12,50 EUR pro Stunde") is None


def test_profile_vector_store_returns_relevant_context(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("job_agent.memory.profile_index.settings.embedding_model", "")
    index = ProfileVectorStore(path=tmp_path / "chroma")
    index.upsert_profile(_profile())

    snippets = index.query("RAG LLM Python automation", top_k=2)

    assert snippets
    assert any("RAG" in snippet or "rag" in snippet.lower() for snippet in snippets)


def test_llm_matcher_falls_back_when_llm_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def broken_llm():
        raise RuntimeError("no local model")

    monkeypatch.setattr("job_agent.agents.matcher.call_llm", broken_llm)

    [match] = run_matcher([_job()], _profile(), use_llm=True)

    assert isinstance(match, MatchResult)
    assert match.score >= 0.9
    assert match.rationale.startswith("LLM fallback:")


def test_llm_writer_falls_back_without_sprint1_note(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def broken_llm():
        raise RuntimeError("no local model")

    monkeypatch.setattr("job_agent.agents.writer.call_llm", broken_llm)
    match = MatchResult(
        job_id="job-1",
        score=1.0,
        matched_skills=["python", "rag"],
        missing_skills=[],
        rationale="2/2 required skills matched.",
    )

    app = run_writer(_job(), match, _profile(), use_llm=True)

    assert app.job_id == "job-1"
    assert "Sprint-1 template draft" not in app.cover_letter_md
    assert app.quality_checks["no_sprint_note"] is True


def test_template_writer_uses_contact_person_from_job_description() -> None:
    job = _job().model_copy(
        update={
            "description": (
                "Ansprechpartnerin: Frau Miriam Schneider. "
                "Im Team werden LLM-Workflows und RAG-Prototypen gebaut."
            )
        }
    )
    match = MatchResult(
        job_id="job-1",
        score=1.0,
        matched_skills=["python", "rag"],
        missing_skills=[],
        rationale="2/2 required skills matched.",
    )

    app = run_writer(job, match, _profile(), use_llm=False)

    assert "Sehr geehrte Frau Miriam Schneider" in app.cover_letter_md
    assert "die Arbeit mit python, rag" in app.cover_letter_md
