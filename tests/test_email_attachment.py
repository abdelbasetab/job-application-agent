"""Optional CV (lebenslauf.pdf) attachment on the application email."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import web
from job_agent.web import WebState, _run_pipeline_from_payload


def _dry_run_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_dry_run", True)
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_demo_recipient", "demo@x.de")
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_from", "sender@x.de")


def _pipeline(state: WebState, db_path: Path) -> str:
    resp = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "draft_all": True,
            "reset_db": True,
            "db_path": str(db_path),
        },
        state,
    )
    return str(resp["jobs"][0]["id"])


def test_email_attaches_cv_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    _dry_run_email(monkeypatch)
    state = WebState()
    web._use_demo_profile(state)
    db_path = tmp_path / "data" / "mail.db"
    job_id = _pipeline(state, db_path)

    out = web._send_application_email_from_payload(
        {"db_path": str(db_path), "job_id": job_id, "attach_cv": True}, state
    )
    assert out["ok"] is True
    assert "lebenslauf.pdf" in out["email"]["attachments"]
    assert "Anhang: lebenslauf.pdf" in out["status"]["notes"]
    cv = web._output_dir(None, job_id) / "lebenslauf.pdf"
    assert cv.read_bytes()[:4] == b"%PDF"


def test_email_attaches_uploaded_cv_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    _dry_run_email(monkeypatch)
    state = WebState()
    db_path = tmp_path / "data" / "mail_uploaded.db"
    job_id = _pipeline(state, db_path)
    upload_dir = tmp_path / "data" / "uploads"
    upload_dir.mkdir(parents=True)
    uploaded = upload_dir / "lebenslauf_upload.pdf"
    uploaded.write_bytes(b"%PDF-original-upload")
    with state.lock:
        state.session(None).uploaded_cv_path = str(uploaded)

    out = web._send_application_email_from_payload(
        {"db_path": str(db_path), "job_id": job_id, "attach_cv": True}, state
    )
    cv = web._output_dir(None, job_id) / "lebenslauf.pdf"

    assert out["ok"] is True
    assert out["email"]["attachments"] == ["lebenslauf.pdf"]
    assert cv.read_bytes() == b"%PDF-original-upload"


def test_email_has_no_attachment_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    _dry_run_email(monkeypatch)
    state = WebState()
    db_path = tmp_path / "data" / "mail2.db"
    job_id = _pipeline(state, db_path)

    out = web._send_application_email_from_payload(
        {"db_path": str(db_path), "job_id": job_id}, state
    )
    assert out["email"]["attachments"] == []
