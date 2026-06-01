"""Integration tests for the Scout agent against a real LLM provider.

Skipped by default. Run with:

    pytest -m integration

For the default Ollama setup, this requires:
    - `ollama serve` running on http://localhost:11434
    - `ollama pull qwen2.5:7b-instruct`
"""

from __future__ import annotations

import pytest

from job_agent.agents.scout import run_scout
from job_agent.schemas import JobPosting, UserProfile
from job_agent.schemas.profile import Preferences


@pytest.mark.integration
def test_scout_returns_valid_postings_from_real_llm() -> None:
    profile = UserProfile(
        name="Integration Tester",
        headline="AI Engineering Student",
        email="i@example.com",
        location="Gelsenkirchen, DE",
        languages={"de": "C1", "en": "C1"},
        skills=["python", "llms", "git"],
        preferences=Preferences(
            locations=["Gelsenkirchen", "Remote"],
            employment_types=["working-student", "internship"],
        ),
    )

    postings = run_scout(profile, query="Werkstudent KI", limit=3)

    assert len(postings) >= 1
    assert all(isinstance(p, JobPosting) for p in postings)
    assert all(p.source == "manual" for p in postings)
