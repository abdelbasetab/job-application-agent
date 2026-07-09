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


def test_matcher_returns_rubric_and_skill_synonyms() -> None:
    job = _job().model_copy(
        update={
            "requirements": ["PostgreSQL", "LLM"],
            "nice_to_have": ["Chroma DB"],
            "description": "Python services with PostgreSQL, LLM workflows and RAG.",
        }
    )

    [match] = run_matcher([job], _profile(), use_llm=False)

    assert match.score >= 0.8
    assert {"sql", "llms"}.issubset(set(match.matched_skills))
    assert match.score_components
    assert {item.key for item in match.score_components} >= {
        "hard_skills",
        "location",
        "posting_quality",
    }
    assert match.risk_level == "low"


def test_matcher_flags_high_risk_ghost_job() -> None:
    suspicious = JobPosting(
        id="ghost-1",
        source="manual",
        source_id="ghost-1",
        url="https://example.com/ghost-1",
        title="Heimarbeit Job Angebot",
        company="Vertraulich",
        location="Remote",
        description="Schnell Geld per WhatsApp. Keine Erfahrung notwendig.",
        requirements=[],
    )

    [match] = run_matcher([suspicious], _profile(), use_llm=False)

    assert match.risk_level == "high"
    assert match.recommendation == "skip"
    assert match.risk_flags
    assert match.score < 0.35


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


def test_matcher_fuzzy_tier_bridges_near_duplicate_skills() -> None:
    """Tier 2: 'python3' in the ad must map onto 'python' in the profile."""
    job = _job().model_copy(update={"requirements": ["python3", "rag"]})

    [match] = run_matcher([job], _profile(), use_llm=False)

    assert "python3" in match.matched_skills
    assert not match.missing_skills
    hard = next(c for c in match.score_components if c.key == "hard_skills")
    assert "python3 ≈ python" in hard.evidence


def test_llm_matcher_runs_parallel_and_preserves_order(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """One LLM call per job, executed concurrently — order must stay stable."""
    import json as _json

    scores = {"j1": 0.91, "j2": 0.52, "j3": 0.73}

    def fake_llm(messages, **_kwargs):  # type: ignore[no-untyped-def]
        payload = _json.loads(messages[1]["content"].split("\n", 1)[1])
        job_id = payload["job"]["id"]
        return _json.dumps(
            {
                "job_id": job_id,
                "score": scores[job_id],
                "matched_skills": [],
                "missing_skills": [],
                "rationale": "stubbed",
            }
        )

    monkeypatch.setattr("job_agent.agents.matcher.call_llm", fake_llm)
    jobs = [
        _job().model_copy(update={"id": job_id, "source_id": job_id})
        for job_id in ("j1", "j2", "j3")
    ]

    results = run_matcher(jobs, _profile(), use_llm=True)

    assert [m.job_id for m in results] == ["j1", "j2", "j3"]
    assert [m.score for m in results] == [0.91, 0.52, 0.73]


def test_writer_self_corrects_failed_quality_checks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A draft with a forbidden phrase triggers exactly one revision pass."""
    import json as _json

    bad_letter = (
        "Sehr geehrte Damen und Herren,\n\n"
        "hiermit bewerbe ich mich als Werkstudent KI Automation bei Example GmbH. "
        + "Ich arbeite mit Python und RAG-Pipelines an praxisnahen Projekten. " * 3
        + "\n\nMit freundlichen Grüßen\nTest Candidate"
    )
    good_letter = (
        "Sehr geehrte Damen und Herren,\n\n"
        "Ihre Ausschreibung als Werkstudent KI Automation bei Example GmbH passt zu "
        "meinem Profil. "
        + "In Uni-Projekten habe ich RAG-Prototypen mit Python gebaut und dokumentiert. " * 3
        + "\n\nMit freundlichen Grüßen\nTest Candidate"
    )
    calls = {"n": 0}

    def fake_llm(messages, **_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        letter = bad_letter if calls["n"] == 1 else good_letter
        return _json.dumps({"job_id": "job-1", "cover_letter_md": letter})

    monkeypatch.setattr("job_agent.agents.writer.call_llm", fake_llm)
    match = MatchResult(
        job_id="job-1",
        score=0.9,
        matched_skills=["python", "rag"],
        missing_skills=[],
        rationale="stub",
    )

    app = run_writer(_job(), match, _profile(), use_llm=True)

    assert calls["n"] == 2, "failed checks must trigger exactly one revision"
    assert app.quality_checks["no_forbidden_phrases"] is True
    assert "hiermit bewerbe ich mich" not in app.cover_letter_md.lower()


def test_writer_keeps_flags_honest_when_revision_does_not_help(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """If the revision is no better, the result still carries failing flags."""
    import json as _json

    bad_letter = (
        "Sehr geehrte Damen und Herren,\n\n"
        "hiermit bewerbe ich mich als Werkstudent KI Automation bei Example GmbH. "
        + "Ich arbeite mit Python und RAG-Pipelines an praxisnahen Projekten. " * 3
        + "\n\nMit freundlichen Grüßen\nTest Candidate"
    )
    calls = {"n": 0}

    def fake_llm(messages, **_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return _json.dumps({"job_id": "job-1", "cover_letter_md": bad_letter})

    monkeypatch.setattr("job_agent.agents.writer.call_llm", fake_llm)
    match = MatchResult(
        job_id="job-1",
        score=0.9,
        matched_skills=["python"],
        missing_skills=[],
        rationale="stub",
    )

    app = run_writer(_job(), match, _profile(), use_llm=True)

    assert calls["n"] == 2
    assert app.quality_checks["no_forbidden_phrases"] is False


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
