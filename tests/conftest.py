"""Shared pytest fixtures.

The default Scout makes a real LLM call. For unit tests we don't want that —
it would be slow, non-deterministic, and require Ollama/Internet. So we
autouse a fixture that patches the Scout to return a fixed list of postings.

Tests that need the real LLM call (and therefore depend on a running Ollama
daemon) opt out by adding ``@pytest.mark.integration``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from job_agent.schemas import JobPosting


def _stub_jobs() -> list[JobPosting]:
    return [
        JobPosting(
            id="stub-001",
            source="manual",
            source_id="stub-001",
            url="https://example.de/jobs/1",
            title="Werkstudent KI (m/w/d)",
            company="Beispiel KI GmbH",
            location="Gelsenkirchen",
            description="Mitarbeit an LLM-Pipelines.",
            requirements=["python", "git"],
            nice_to_have=["docker"],
            employment_type="working-student",
            remote=False,
        ),
        JobPosting(
            id="stub-002",
            source="manual",
            source_id="stub-002",
            url="https://example.de/jobs/2",
            title="Praktikant Machine Learning",
            company="Test Tech AG",
            location="Dortmund",
            description="Klassifikations- und Embedding-Projekte.",
            requirements=["python", "llms", "machine learning"],
            employment_type="internship",
            remote=True,
        ),
        JobPosting(
            id="stub-003",
            source="manual",
            source_id="stub-003",
            url="https://example.de/jobs/3",
            title="Werkstudent Datenanalyse",
            company="Demo Data Solutions",
            location="Essen",
            description="SQL-getriebene Reporting-Pipelines.",
            requirements=["sql", "airflow"],
            employment_type="working-student",
            remote=False,
        ),
    ]


@pytest.fixture(autouse=True)
def stub_scout(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Replace run_scout with a deterministic stub for every test.

    Tests marked ``integration`` skip the patch so they exercise the real LLM.
    """
    if request.node.get_closest_marker("integration") is not None:
        yield
        return

    def fake_run_scout(profile, query=None, limit=5):  # type: ignore[no-untyped-def]
        return _stub_jobs()[:limit]

    monkeypatch.setattr("job_agent.pipeline.run_scout", fake_run_scout)
    monkeypatch.setattr("job_agent.agents.scout.run_scout", fake_run_scout)
    yield
