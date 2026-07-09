"""Offline tests for the tracker pattern analysis."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, JobPosting
from job_agent.tools.patterns import analyze_patterns

_NOW = datetime(2026, 7, 10, 12, 0, 0)


def _job(job_id: str, title: str, company: str, source: str = "manual") -> JobPosting:
    return JobPosting(
        id=job_id,
        source=source,  # type: ignore[arg-type]
        source_id=job_id,
        url=f"https://example.de/jobs/{job_id}",
        title=title,
        company=company,
        location="Essen",
        description="Beschreibung für Tests.",
        requirements=["python"],
    )


def _status(
    job_id: str,
    stage: str,
    submitted_days_ago: int | None,
    updated_days_ago: int,
) -> ApplicationStatus:
    return ApplicationStatus(
        job_id=job_id,
        status=stage,  # type: ignore[arg-type]
        submitted_at=(_NOW - timedelta(days=submitted_days_ago)) if submitted_days_ago else None,
        updated_at=_NOW - timedelta(days=updated_days_ago),
        notes="",
    )


def test_analyze_patterns_empty_store(tmp_path: Path) -> None:
    store = Store(tmp_path / "empty.db")
    report = analyze_patterns(store, now=_NOW)
    assert report["total"] == 0
    assert report["response_rate"] is None
    assert report["insights"], "auch ohne Daten gibt es eine Handlungsempfehlung"
    store.close()


def test_analyze_patterns_funnel_rates_and_stale(tmp_path: Path) -> None:
    store = Store(tmp_path / "patterns.db")
    seed = [
        ("p1", "draft", None, 1),
        ("p2", "submitted", 20, 20),   # stale: seit 20 Tagen keine Bewegung
        ("p3", "submitted", 3, 3),     # frisch
        ("p4", "interview", 10, 4),    # Antwort nach 6 Tagen
        ("p5", "rejected", 12, 4),     # Antwort nach 8 Tagen
        ("p6", "offer", 30, 16),       # Antwort nach 14 Tagen
    ]
    for job_id, stage, submitted, updated in seed:
        store.save_job(_job(job_id, f"Job {job_id}", "RuhrTech GmbH"))
        store.upsert_status(_status(job_id, stage, submitted, updated))

    report = analyze_patterns(store, now=_NOW)

    assert report["total"] == 6
    assert report["funnel"]["draft"] == 1
    assert report["funnel"]["submitted"] == 2
    assert report["sent_total"] == 5  # submitted + interview + rejected + offer
    assert report["response_rate"] == round(3 / 5, 3)
    assert report["interview_rate"] == round(2 / 5, 3)
    assert report["avg_days_to_response"] == round((6 + 8 + 14) / 3, 1)

    stale_ids = [item["job_id"] for item in report["stale_submitted"]]
    assert stale_ids == ["p2"], "nur die 20-Tage-Bewerbung ist überfällig"

    assert report["top_companies"][0]["company"] == "RuhrTech GmbH"
    assert report["insights"]
    store.close()
