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


def test_profile_vector_store_persists_across_instances(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("job_agent.memory.profile_index.settings.embedding_model", "")
    index_path = tmp_path / "profile-index"
    ProfileVectorStore(path=index_path).upsert_profile(_profile())

    reopened = ProfileVectorStore(path=index_path)

    assert reopened.query("Python RAG", top_k=1)


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
                    "matched_skills": ["python", "rag"],
                    "missing_skills": [],
                    "rationale": "stubbed",
                    "recommendation": (
                        "strong" if scores[job_id] >= 0.8 else "good" if scores[job_id] >= 0.6 else "maybe"
                    ),
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


def test_writer_uses_safe_template_when_revision_does_not_help(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An unsafe revision is never returned to the user."""
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
    assert app.quality_checks["no_forbidden_phrases"] is True
    assert app.generation_method == "template"


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


def test_skill_aliases_use_token_boundaries() -> None:
    profile = _profile().model_copy(update={"skills": ["machine learning"]})
    for requirement in ("html", "html5", "xml", "yaml"):
        job = _job().model_copy(update={"requirements": [requirement]})
        [match] = run_matcher([job], profile, use_llm=False)
        assert match.matched_skills == []
        assert match.score == 0.0


def test_missing_requirements_are_capped_below_draft_threshold() -> None:
    job = _job().model_copy(
        update={
            "requirements": [],
            "requirements_raw": "",
            "description": "Eine ausfuehrliche Rolle ohne klar benannte technische Muss-Anforderungen. " * 3,
        }
    )
    [match] = run_matcher([job], _profile(), use_llm=False)
    assert match.score <= 0.49
    assert match.recommendation in {"maybe", "skip"}


def test_language_level_and_location_are_not_substring_matches() -> None:
    profile = _profile().model_copy(
        update={
            "languages": {"de": "A1", "en": "C1"},
            "preferences": Preferences(locations=["Essen"]),
        }
    )
    job = _job().model_copy(
        update={
            "location": "Hessen",
            "description": "Fuer diese Position sind Deutschkenntnisse auf Niveau C1 erforderlich.",
        }
    )
    [match] = run_matcher([job], profile, use_llm=False)
    components = {component.key: component for component in match.score_components}
    assert components["location"].score == 2
    assert components["language"].score == 2
    assert "A1 statt C1" in components["language"].evidence


def test_excluded_company_and_minimum_salary_are_hard_gates() -> None:
    excluded = _profile().model_copy(
        update={"preferences": Preferences(excluded_companies=["Example GmbH"])}
    )
    [company_match] = run_matcher([_job()], excluded, use_llm=False)
    assert company_match.score == 0.0
    assert company_match.recommendation == "skip"

    salary = _profile().model_copy(
        update={"preferences": Preferences(min_salary=80_000)}
    )
    [salary_match] = run_matcher([_job()], salary, use_llm=False)
    assert salary_match.score == 0.0
    assert "Gehaltsobergrenze" in salary_match.score_summary


def test_llm_matcher_rejects_wrong_job_id(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import json as _json

    monkeypatch.setattr(
        "job_agent.agents.matcher.call_llm",
        lambda *_args, **_kwargs: _json.dumps(
            {
                "job_id": "another-job",
                "score": 1.0,
                "matched_skills": ["python", "rag"],
                "missing_skills": [],
                "rationale": "invalid id",
                "recommendation": "strong",
            }
        ),
    )
    [match] = run_matcher([_job()], _profile(), use_llm=True)
    assert match.job_id == _job().id
    assert match.rationale.startswith("LLM fallback:")


def test_template_writer_never_exposes_matcher_analysis() -> None:
    match = MatchResult(
        job_id="job-1",
        score=0.7,
        matched_skills=["python"],
        missing_skills=["docker"],
        rationale="Gesamtbewertung 0.70. Risiko-Hinweise: Ghost-Job. Fehlend: Docker.",
    )
    app = run_writer(_job(), match, _profile(), use_llm=False)
    lowered = app.cover_letter_md.casefold()
    assert "gesamtbewertung" not in lowered
    assert "ghost-job" not in lowered
    assert "fehlend" not in lowered
    assert "docker" not in lowered
    assert all(app.quality_checks.values())
