"""Sanity tests for the SQLite store."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from job_agent.memory.store import Store
from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
    MatchResult,
    UserProfile,
)


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


def test_profile_match_and_status_history_survive_restart(tmp_path: Path) -> None:
    db = tmp_path / "persistent.db"
    profile = UserProfile(
        name="Test Person",
        headline="Data Engineer",
        email="test@example.invalid",
        location="Berlin",
        languages={"de": "C1"},
        skills=["Python", "SQL"],
    )
    match = MatchResult(
        job_id="job-1",
        score=0.8,
        rationale="Guter fachlicher Match.",
        matched_skills=["Python"],
        recommendation="good",
    )
    store = Store(db)
    fingerprint = store.save_profile(profile, "cv")
    store.save_match(match, fingerprint)
    store.upsert_status(ApplicationStatus(job_id="job-1", status="draft"))
    store.upsert_status(ApplicationStatus(job_id="job-1", status="submitted"))
    store.close()

    reopened = Store(db)
    try:
        active = reopened.get_active_profile()
        assert active == (profile, "cv", fingerprint)
        assert reopened.get_match("job-1") == match
        events = reopened.status_events("job-1")
        assert [event["new_status"] for event in reversed(events)] == ["draft", "submitted"]
    finally:
        reopened.close()


def test_email_inbox_and_outbox_are_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "mail.db")
    try:
        assert store.record_processed_email(
            "message-1",
            uid="42",
            message_id="<message-1@example.invalid>",
            received_at=None,
            job_id="job-1",
            stage="interview",
            payload={"subject": "Einladung"},
        )
        assert not store.record_processed_email(
            "message-1",
            uid="42",
            message_id="<message-1@example.invalid>",
            received_at=None,
            job_id="job-1",
            stage="interview",
            payload={},
        )
        assert store.reserve_email(
            "send-1",
            job_id="job-1",
            event_type="application",
            recipient="hr@example.invalid",
            payload={"subject": "Bewerbung"},
        )
        assert not store.reserve_email(
            "send-1",
            job_id="job-1",
            event_type="application",
            recipient="hr@example.invalid",
            payload={},
        )
        assert store.reserve_email(
            "send-2",
            job_id="job-1",
            event_type="application",
            recipient="hr@example.invalid",
            payload={"subject": "Dry-run"},
        )
        store.finish_email("send-2", state="dry_run", message_id="msg-dry-run")
        assert store.reserve_email(
            "send-2",
            job_id="job-1",
            event_type="application",
            recipient="hr@example.invalid",
            payload={"subject": "Real send"},
            allow_retry_from_dry_run=True,
        )
        entry = store.email_outbox_entry("send-2")
        assert entry is not None
        assert entry["state"] == "pending"
        assert entry["payload"]["subject"] == "Real send"
        store.finish_email("send-1", state="sent", message_id="message-1")
        assert store.email_outbox_entry("send-1")["state"] == "sent"  # type: ignore[index]
    finally:
        store.close()


def test_clear_pipeline_results_is_atomic_and_keeps_profile_and_mail_audit(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "reset.db")
    profile = UserProfile(
        name="Test Person",
        headline="Data Engineer",
        email="test@example.invalid",
        location="Berlin",
        languages={"de": "C1"},
        skills=["Python"],
    )
    job = JobPosting(
        id="reset-1",
        source="manual",
        source_id="reset-1",
        url="https://example.com/reset-1",
        title="Data Engineer",
        company="Example GmbH",
        location="Berlin",
        description="Python",
    )
    fingerprint = store.save_profile(profile, "cv")
    store.save_job(job)
    store.save_match(
        MatchResult(job_id=job.id, score=0.8, rationale="Guter Match."), fingerprint
    )
    store.save_application(
        GeneratedApplication(job_id=job.id, cover_letter_md="Anschreiben")
    )
    store.upsert_status(ApplicationStatus(job_id=job.id))
    store.record_email_audit("dry_run", {"sent": False}, job_id=job.id)

    store.clear_pipeline_results()

    assert store.all_jobs() == []
    assert store.all_matches() == []
    assert store.get_application(job.id) is None
    assert store.all_status() == []
    assert store.status_events() == []
    assert store.get_active_profile() == (profile, "cv", fingerprint)
    assert len(store.email_audit()) == 1
    store.close()
