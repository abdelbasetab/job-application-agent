"""Offline tests for the follow-up cadence (Tracker Sprint 4)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from job_agent.agents.tracker import due_follow_ups, record_follow_up
from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, JobPosting

_NOW = datetime(2026, 7, 1, 12, 0, 0)


def _job(job_id: str, title: str, company: str) -> JobPosting:
    return JobPosting(
        id=job_id,
        source="manual",
        source_id=job_id,
        url=f"https://example.de/jobs/{job_id}",
        title=title,
        company=company,
        location="Essen",
        description="Beispielbeschreibung für Tests.",
        requirements=["python"],
    )


def _status(job_id: str, status: str, days_ago: int) -> ApplicationStatus:
    stamp = _NOW - timedelta(days=days_ago)
    return ApplicationStatus(
        job_id=job_id,
        status=status,  # type: ignore[arg-type]
        submitted_at=stamp if status == "submitted" else None,
        updated_at=stamp,
        notes="",
    )


@pytest.fixture
def seeded_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "followups.db")
    store.save_job(_job("fu-old", "Werkstudent KI", "RuhrTech GmbH"))
    store.save_job(_job("fu-older", "Praktikum ML", "Westfalen Data"))
    store.save_job(_job("fu-fresh", "Werkstudent BI", "Emscher Analytics"))
    store.save_job(_job("fu-draft", "Werkstudent Cloud", "Cloud AG"))
    store.upsert_status(_status("fu-old", "submitted", days_ago=10))
    store.upsert_status(_status("fu-older", "submitted", days_ago=21))
    store.upsert_status(_status("fu-fresh", "submitted", days_ago=2))
    store.upsert_status(_status("fu-draft", "draft", days_ago=30))
    return store


def test_due_follow_ups_selects_only_stale_submitted(seeded_store: Store) -> None:
    items = due_follow_ups(seeded_store, days=7, candidate_name="Test Candidate", now=_NOW)

    assert [item.job_id for item in items] == ["fu-older", "fu-old"], "most overdue first"
    oldest = items[0]
    assert oldest.days_since_activity == 21
    assert oldest.days_overdue == 14
    assert oldest.company == "Westfalen Data"
    seeded_store.close()


def test_follow_up_email_draft_is_complete(seeded_store: Store) -> None:
    [_, item] = due_follow_ups(seeded_store, days=7, candidate_name="Test Candidate", now=_NOW)

    assert "Nachfrage" in item.suggested_email_md
    assert "Werkstudent KI" in item.suggested_email_md
    assert "RuhrTech GmbH" in item.suggested_email_md
    assert "Test Candidate" in item.suggested_email_md
    assert "Mit freundlichen Grüßen" in item.suggested_email_md
    seeded_store.close()


def test_record_follow_up_resets_the_clock(seeded_store: Store) -> None:
    record = record_follow_up(seeded_store, "fu-old", now=_NOW)

    assert record.status == "submitted", "status must not change"
    assert record.submitted_at is not None, "submitted_at must be preserved"
    assert "Follow-up" in record.notes

    items = due_follow_ups(seeded_store, days=7, candidate_name="x", now=_NOW)
    assert [item.job_id for item in items] == ["fu-older"], "fu-old is no longer due"
    seeded_store.close()


def test_record_follow_up_unknown_job_raises(seeded_store: Store) -> None:
    with pytest.raises(ValueError, match="No tracked application"):
        record_follow_up(seeded_store, "does-not-exist", now=_NOW)
    seeded_store.close()
