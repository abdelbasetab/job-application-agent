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
def offline_defaults(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Make every non-integration test deterministic and network-free.

    Two things would otherwise leak the ambient environment into the "offline"
    suite:

    * the default Scout makes a real LLM call — we stub it with fixed postings;
    * Matcher/Writer follow ``settings.enable_llm_agents``, so a developer whose
      ``.env`` sets ``ENABLE_LLM_AGENTS=true`` would silently hit the real LLM,
      making score assertions slow and flaky. We force the agent defaults off.

    Tests that exercise the LLM paths pass ``use_llm=True`` explicitly (and mock
    ``call_llm``), so they override these defaults. Tests marked ``integration``
    opt out entirely and talk to the real services.
    """
    if request.node.get_closest_marker("integration") is not None:
        yield
        return

    def fake_run_scout(profile, query=None, limit=5):  # type: ignore[no-untyped-def]
        return _stub_jobs()[:limit]

    monkeypatch.setattr("job_agent.pipeline.run_scout", fake_run_scout)
    monkeypatch.setattr("job_agent.agents.scout.run_scout", fake_run_scout)
    monkeypatch.setattr("job_agent.utils.config.settings.enable_llm_agents", False)
    monkeypatch.setattr("job_agent.utils.config.settings.enable_chroma", False)
    yield
