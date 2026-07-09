from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, GeneratedApplication, JobPosting
from job_agent.tools.email_sync import (
    InboxMessage,
    classify_message,
    match_message_to_job,
    sync_messages,
)


def _job() -> JobPosting:
    return JobPosting(
        id="job-sync-1",
        source="manual",
        source_id="job-sync-1",
        url="https://example.com/jobs/sync-1",
        title="Werkstudent KI Automation",
        company="Example GmbH",
        location="Essen",
        description="Python role.",
        requirements=["python"],
    )


def test_classify_message_detects_common_application_replies() -> None:
    assert classify_message("Ihre Bewerbung", "Vielen Dank für Ihre Bewerbung.") == "submitted"
    assert classify_message("Einladung", "Wir möchten Sie zu einem Vorstellungsgespräch einladen.") == "interview"
    assert classify_message("Ihre Bewerbung", "Leider müssen wir Ihnen eine Absage senden.") == "rejected"
    assert classify_message("Angebot", "Wir freuen uns, Ihnen ein Angebot zu machen.") == "offer"
    assert classify_message("Newsletter", "Neue Jobs in Ihrer Nähe") == "unknown"


def test_match_message_to_job_uses_company_and_title() -> None:
    message = InboxMessage(
        uid="1",
        sender="hr@example.com",
        subject="Example GmbH - Werkstudent KI Automation",
        body="Vielen Dank für Ihre Bewerbung.",
    )

    assert match_message_to_job(message, [_job()]) == _job()


def test_sync_messages_updates_status_when_not_dry_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "sync.db")
    job = _job()
    store.save_job(job)
    store.save_application(
        GeneratedApplication(
            job_id=job.id,
            cover_letter_md="Bewerbung",
            generated_at=date.today(),
        )
    )
    message = InboxMessage(
        uid="1",
        sender="hr@example.com",
        subject="Example GmbH - Werkstudent KI Automation",
        body="Wir möchten Sie zu einem Vorstellungsgespräch einladen.",
    )

    result = sync_messages(store, [message], dry_run=False)
    status = store.get_status(job.id)
    store.close()

    assert result["updates"][0]["stage"] == "interview"
    assert status is not None
    assert status.status == "interview"
    assert "Inbox: interview erkannt" in status.notes


def test_sync_messages_falls_back_to_single_active_application(tmp_path: Path) -> None:
    store = Store(tmp_path / "sync-fallback.db")
    job = _job()
    store.save_job(job)
    store.save_application(
        GeneratedApplication(
            job_id=job.id,
            cover_letter_md="Bewerbung",
            generated_at=date.today(),
        )
    )
    store.upsert_status(
        ApplicationStatus(
            job_id=job.id,
            status="submitted",
            submitted_at=datetime.now(),
        )
    )
    message = InboxMessage(
        uid="2",
        sender="miriam.schneider@recruiting.test",
        subject="Einladung",
        body="Vielen Dank fuer Ihre Bewerbung. Wir moechten Sie gerne zu einem Interview einladen.",
    )

    result = sync_messages(store, [message], dry_run=False)
    status = store.get_status(job.id)
    store.close()

    assert result["seen"] == 1
    assert result["classified"] == 1
    assert result["matched"] == 1
    assert result["updates"][0]["match_method"] == "tracked_application"
    assert status is not None
    assert status.status == "interview"
