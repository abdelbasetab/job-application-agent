"""End-to-end tracer bullet — proves all four agents talk to each other.

Sprint 2: Scout now performs real HTTP / LLM calls. We mock it out here so
this suite stays fully offline. The real Scout is exercised in
`test_scout_integration.py` (only when `pytest -m integration` is passed).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_agent.memory.store import Store
from job_agent.pipeline import run_pipeline
from job_agent.schemas import JobPosting, UserProfile
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


def _fake_jobs() -> list[JobPosting]:
    """Three jobs covering different score buckets for the matcher."""
    return [
        JobPosting(
            id="fake-1",
            source="manual",
            source_id="fake-1",
            url="https://example.com/jobs/1",  # type: ignore[arg-type]
            title="Junior Python Engineer",
            company="Example GmbH",
            location="Berlin",
            description="Python role.",
            requirements=["python", "git"],
            nice_to_have=["llms"],
        ),
        JobPosting(
            id="fake-2",
            source="manual",
            source_id="fake-2",
            url="https://example.com/jobs/2",  # type: ignore[arg-type]
            title="ML Working Student",
            company="Beispiel AG",
            location="Berlin",
            description="ML role.",
            requirements=["python", "llms", "git", "sql"],
            nice_to_have=[],
        ),
        JobPosting(
            id="fake-3",
            source="manual",
            source_id="fake-3",
            url="https://example.com/jobs/3",  # type: ignore[arg-type]
            title="Rust Backend Engineer",
            company="Drittes Unternehmen",
            location="Berlin",
            description="Rust role.",
            requirements=["rust", "tokio", "wasm"],
            nice_to_have=[],
        ),
    ]


@pytest.fixture
def mocked_scout(monkeypatch: pytest.MonkeyPatch) -> list[JobPosting]:
    """Replace pipeline.run_scout with a deterministic stub. Returns the fixtures."""
    jobs = _fake_jobs()

    def _stub(profile: UserProfile, query: str | None = None, limit: int = 5, **_: Any) -> list[JobPosting]:
        return jobs[:limit]

    monkeypatch.setattr("job_agent.pipeline.run_scout", _stub)
    return jobs


def test_pipeline_runs_end_to_end(tmp_path: Path, mocked_scout: list[JobPosting]) -> None:
    store = Store(tmp_path / "test.db")
    result = run_pipeline(profile=_profile(), store=store, match_threshold=0.3)

    assert len(result.jobs) >= 3
    assert len(result.matches) == len(result.jobs)
    assert all(0.0 <= m.score <= 1.0 for m in result.matches)
    assert len(result.applications) >= 1, "no matches passed the threshold"
    assert len(result.statuses) == len(result.applications)
    assert all(s.status == "draft" for s in result.statuses)

    persisted = store.all_status()
    assert len(persisted) == len(result.statuses)
    store.close()


def test_matcher_skill_overlap_scoring(
    tmp_path: Path, mocked_scout: list[JobPosting]
) -> None:
    """Matcher must score 1.0 when every requirement is matched."""
    store = Store(tmp_path / "test.db")
    profile = UserProfile(
        name="x",
        headline="x",
        email="x@example.com",
        location="Berlin",
        languages={"de": "C1"},
        skills=["python", "llms", "git", "sql", "machine learning", "airflow"],
    )
    result = run_pipeline(profile=profile, store=store, match_threshold=0.99)
    # fake-2's requirements (python, llms, git, sql) are fully covered.
    assert any(m.score >= 0.99 for m in result.matches)
    store.close()


def test_threshold_zero_drafts_every_found_job(
    tmp_path: Path, mocked_scout: list[JobPosting]
) -> None:
    store = Store(tmp_path / "test.db")
    result = run_pipeline(profile=_profile(), store=store, match_threshold=0.0)

    assert len(result.jobs) == len(mocked_scout)
    assert len(result.applications) == len(result.jobs)
    assert any(m.score == 0 for m in result.matches)
    store.close()


def test_dedup_guard_skips_already_applied(
    tmp_path: Path, mocked_scout: list[JobPosting]
) -> None:
    """Second pipeline run must not re-draft applications already in the store."""
    store = Store(tmp_path / "test.db")
    first = run_pipeline(profile=_profile(), store=store, match_threshold=0.3)
    second = run_pipeline(profile=_profile(), store=store, match_threshold=0.3)

    assert len(first.applications) >= 1
    assert len(second.applications) == 0, "dedup guard didn't skip already-applied jobs"
    store.close()
