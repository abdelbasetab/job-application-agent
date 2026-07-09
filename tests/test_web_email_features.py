from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from job_agent import web
from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, GeneratedApplication, JobPosting
from job_agent.web import WebState


def _user() -> web.AuthUser:
    return {"id": 7, "email": "login@example.de", "created_at": "now"}


def _job(job_id: str = "web-email-1") -> JobPosting:
    return JobPosting(
        id=job_id,
        source="manual",
        source_id=job_id,
        url="https://example.de/jobs/1",
        title="Werkstudent Software",
        company="Example GmbH",
        location="Essen",
        description="Bitte senden Sie Ihre Bewerbung an recruiting@example.de.",
        requirements=["python"],
    )


def test_web_config_uses_local_email_credentials(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = WebState()
    user = _user()

    out = web._save_email_credentials_from_payload(
        {
            "email_address": "cv@example.de",
            "smtp_host": "smtp.example.de",
            "smtp_user": "cv@example.de",
            "smtp_password": "secret",
            "imap_host": "imap.example.de",
            "imap_user": "cv@example.de",
            "imap_password": "secret",
        },
        state,
        user,
    )
    config = web._config_payload(state, user)

    assert out["ok"] is True
    assert config["email_identity"]["account_source"] == "local"
    assert config["email_ready"] is True
    assert config["email_sync_ready"] is True


def test_web_email_connection_test_uses_saved_account(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = WebState()
    user = _user()
    web._save_email_credentials_from_payload(
        {
            "email_address": "cv@example.de",
            "smtp_host": "smtp.example.de",
            "smtp_user": "cv@example.de",
            "smtp_password": "secret",
            "imap_host": "imap.example.de",
            "imap_user": "cv@example.de",
            "imap_password": "secret",
        },
        state,
        user,
    )
    seen: dict[str, object] = {}

    def fake_test(account, *, kind="both", timeout=15.0):  # type: ignore[no-untyped-def]
        seen.update({"sender": account.sender, "kind": kind, "timeout": timeout})
        return {
            "ok": True,
            "smtp": {
                "ok": True,
                "configured": True,
                "protocol": "smtp",
                "host": account.smtp_host,
                "port": account.smtp_port,
                "user": account.smtp_user,
                "message": "SMTP Login erfolgreich.",
            },
        }

    monkeypatch.setattr(
        "job_agent.tools.email_connection.test_email_connections",
        fake_test,
    )

    out = web._test_email_connection_from_payload(
        {"kind": "smtp", "timeout": 9},
        state,
        user,
    )

    assert out["ok"] is True
    assert out["smtp"]["ok"] is True
    assert out["account_source"] == "local"
    assert out["email_identity"]["sender"] == "cv@example.de"
    assert seen == {"sender": "cv@example.de", "kind": "smtp", "timeout": 9.0}


def test_follow_up_email_uses_job_contact_when_recipient_missing(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_dry_run", True)
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_demo_recipient", "")
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_from", "sender@example.de")
    db_path = tmp_path / "data" / "web_email.db"
    store = Store(db_path)
    job = _job()
    try:
        store.save_job(job)
        store.save_application(
            GeneratedApplication(job_id=job.id, cover_letter_md="Bewerbung", generated_at=date.today())
        )
        store.upsert_status(
            ApplicationStatus(
                job_id=job.id,
                status="submitted",
                submitted_at=datetime.now() - timedelta(days=10),
            )
        )
    finally:
        store.close()

    out = web._send_follow_up_email_from_payload(
        {"db_path": str(db_path), "job_id": job.id},
        WebState(),
    )

    assert out["ok"] is True
    assert out["email"]["recipient"] == "recruiting@example.de"
    assert out["email"]["dry_run"] is True
