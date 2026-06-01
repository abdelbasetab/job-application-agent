"""End-to-end tracer bullet — proves all four agents talk to each other."""

from __future__ import annotations

from pathlib import Path

from job_agent.memory.store import Store
from job_agent.pipeline import run_pipeline
from job_agent.schemas import UserProfile
from job_agent.schemas.profile import Preferences


def _profile() -> UserProfile:
    return UserProfile(
        name="Test Candidate",
        headline="Test Engineer",
        email="t@example.com",
        location="Berlin",
        languages={"de": "C1", "en": "C1"},
        skills=["python", "llms", "git", "sql"],
        preferences=Preferences(locations=["Berlin", "Remote"]),
    )


def test_pipeline_runs_end_to_end(tmp_path: Path) -> None:
    store = Store(tmp_path / "test.db")
    result = run_pipeline(profile=_profile(), store=store, match_threshold=0.3)

    # Scout produced jobs.
    assert len(result.jobs) >= 3

    # Matcher scored every job.
    assert len(result.matches) == len(result.jobs)
    assert all(0.0 <= m.score <= 1.0 for m in result.matches)

    # At least one match qualified for Writer.
    assert len(result.applications) >= 1, "no matches passed the threshold"

    # Tracker persisted every draft.
    assert len(result.statuses) == len(result.applications)
    assert all(s.status == "draft" for s in result.statuses)

    # SQLite contains what we expect.
    persisted = store.all_status()
    assert len(persisted) == len(result.statuses)
    store.close()


def test_matcher_skill_overlap_scoring(tmp_path: Path) -> None:
    """Matcher must score 1.0 when every requirement is matched."""
    store = Store(tmp_path / "test.db")
    profile = UserProfile(
        name="x",
        headline="x",
        email="x@example.com",
        location="Berlin",
        languages={"de": "C1"},
        skills=["python", "llms", "git", "machine learning", "sql", "airflow"],
    )
    result = run_pipeline(profile=profile, store=store, match_threshold=0.99)
    # With all skills, at least one job should score perfect (the stub matches python+llms+git fully).
    assert any(m.score >= 0.99 for m in result.matches)
    store.close()
