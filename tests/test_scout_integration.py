"""Integration tests for Scout — hit real APIs + a real LLM.

Skipped by default (see pyproject.toml: `addopts = -m 'not integration'`).
Run them with:  pytest -m integration

Prerequisites:
- Ollama running locally with the configured model pulled
  (`ollama pull qwen2.5:7b-instruct`)
- ADZUNA_APP_ID + ADZUNA_APP_KEY in .env (BA-Jobsuche works without keys)
"""

from __future__ import annotations

import pytest

from job_agent.agents.scout import run_scout
from job_agent.schemas import UserProfile
from job_agent.schemas.profile import Preferences
from job_agent.tools.job_search import adzuna_search, ba_jobsuche_search


def _profile() -> UserProfile:
    return UserProfile(
        name="Integration Test",
        headline="AI Engineering Student",
        email="t@example.com",
        location="Gelsenkirchen, DE",
        languages={"de": "C1", "en": "C1"},
        skills=["python", "sql", "git"],
        preferences=Preferences(
            locations=["Berlin", "Remote"],
            employment_types=["working-student", "internship"],
        ),
    )


@pytest.mark.integration
def test_adzuna_search_returns_validated_postings() -> None:
    postings = adzuna_search(query="Python", location="Berlin", limit=3)
    assert isinstance(postings, list)
    for p in postings:
        assert p.source == "adzuna"
        assert str(p.url).startswith("https://")


@pytest.mark.integration
def test_ba_jobsuche_search_returns_validated_postings() -> None:
    postings = ba_jobsuche_search(query="Python", location="Berlin", limit=3)
    assert isinstance(postings, list)
    for p in postings:
        assert p.source == "ba-jobsuche"
        assert str(p.url).startswith("https://")


@pytest.mark.integration
def test_run_scout_combines_real_sources() -> None:
    jobs = run_scout(_profile(), query="Python Berlin", limit=3)
    assert 1 <= len(jobs) <= 3
    assert all(j.source in ("adzuna", "ba-jobsuche") for j in jobs)
    assert len({j.id for j in jobs}) == len(jobs)
