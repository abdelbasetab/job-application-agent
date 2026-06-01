"""Sanity tests for the SQLite store."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, GeneratedApplication, JobPosting


def test_store_round_trip(tmp_path: Path) -> None:
    store = Store(tmp_path / "x.db")

    job = JobPosting(
        id="r-1",
        source="manual",
        source_id="r-1",
        url="https://example.com/r-1",
        title="t",
        company="c",
        location="Berlin",
        description="d",
        requirements=["python"],
    )
    store.save_job(job)
    assert store.get_job("r-1") == job

    app_doc = GeneratedApplication(
        job_id="r-1",
        cover_letter_md="hi",
        generated_at=date.today(),
    )
    store.save_application(app_doc)
    assert store.get_application("r-1") == app_doc

    status = ApplicationStatus(job_id="r-1", status="draft")
    store.upsert_status(status)
    got = store.get_status("r-1")
    assert got is not None
    assert got.status == "draft"
    store.close()
