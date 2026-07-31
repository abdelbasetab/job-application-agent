"""Search-query suggestions derived from the stored CV."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import web
from job_agent.demo_profile import demo_profile
from job_agent.schemas.profile import Education, Experience, Preferences, UserProfile
from job_agent.tools.search_suggestions import MAX_SUGGESTIONS, search_suggestions
from job_agent.web import WebState


def _profile(**overrides: object) -> UserProfile:
    base: dict[str, object] = {
        "name": "Mara Test",
        "headline": "Data Science Student",
        "email": "mara@example.invalid",
        "location": "Essen, DE",
        "languages": {"de": "C1"},
        "skills": ["python", "git", "sql"],
        "experience": [],
        "education": [],
        "preferences": Preferences(employment_types=["working-student"]),
    }
    base.update(overrides)
    return UserProfile(**base)  # type: ignore[arg-type]


def test_suggestions_combine_employment_type_with_headline() -> None:
    queries = [item.query for item in search_suggestions(_profile())]

    # "Student" is stripped so the rest reads like a job title.
    assert "Werkstudent Data Science" in queries
    assert all("Student Data Science" not in query for query in queries)


def test_suggestions_skip_ubiquitous_tools() -> None:
    queries = [item.query for item in search_suggestions(_profile())]

    assert "Werkstudent Python" in queries
    assert "Werkstudent Git" not in queries, "generic tooling must not become a query"


def test_suggestions_uppercase_known_acronyms() -> None:
    queries = [item.query for item in search_suggestions(_profile())]

    assert "Werkstudent SQL" in queries


def test_suggestions_use_first_segment_of_study_field() -> None:
    profile = _profile(
        education=[
            Education(
                degree="B.Sc.",
                institution="Beispiel-Hochschule",
                field="Computer Science / AI",
                start="2023-10",
            )
        ]
    )

    queries = [item.query for item in search_suggestions(profile)]

    assert "Werkstudent Computer Science" in queries


def test_suggestions_include_recent_role_and_carry_a_reason() -> None:
    profile = _profile(
        experience=[
            Experience(role="Data Analyst", company="Beispiel GmbH", start="2024-01"),
        ]
    )

    suggestions = search_suggestions(profile)
    roles = [item for item in suggestions if item.query == "Data Analyst"]

    assert roles, "the most recent role should be offered as a query"
    assert "Beispiel GmbH" in roles[0].reason
    assert all(item.reason for item in suggestions), "every suggestion explains itself"


def test_suggestions_are_deduplicated_and_capped() -> None:
    profile = _profile(
        headline="Python",
        skills=["python", "Python", "PYTHON", "sql", "machine learning"],
        preferences=Preferences(employment_types=["working-student", "internship"]),
    )

    suggestions = search_suggestions(profile)
    queries = [item.query.casefold() for item in suggestions]

    assert len(queries) == len(set(queries))
    assert len(suggestions) <= MAX_SUGGESTIONS


def test_suggestions_without_employment_preference_fall_back_to_bare_terms() -> None:
    profile = _profile(preferences=Preferences(employment_types=[]))

    queries = [item.query for item in search_suggestions(profile)]

    assert "Data Science" in queries
    assert all(not query.startswith(" ") for query in queries)


def test_endpoint_returns_empty_list_without_a_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")

    out = web._search_suggestions_payload(WebState())

    assert out == {"ok": True, "profile_ready": False, "suggestions": []}


def test_endpoint_returns_suggestions_for_the_active_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = WebState()
    web._use_demo_profile(state)

    out = web._search_suggestions_payload(state)

    assert out["ok"] is True
    assert out["profile_ready"] is True
    assert out["suggestions"], "demo profile must yield suggestions"
    assert {"query", "reason"} == set(out["suggestions"][0])
    expected = [item.query for item in search_suggestions(demo_profile())]
    assert [item["query"] for item in out["suggestions"]] == expected
