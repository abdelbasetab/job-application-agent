from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import web
from job_agent.memory.store import Store
from job_agent.web import WebState, _run_pipeline_from_payload


def test_web_auth_register_login_me_logout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "AUTH_DB_PATH", tmp_path / "auth.db")
    monkeypatch.setattr(web.settings, "web_allow_registration", True)

    registered = web._register_from_payload(
        {"email": "demo@example.com", "password": "password-123"}
    )
    token = str(registered["session_token"])
    assert registered["ok"] is True
    assert registered["user"]["email"] == "demo@example.com"

    me = web._auth_me_from_cookie(f"{web.AUTH_COOKIE}={token}")
    assert me["authenticated"] is True
    assert me["user"]["email"] == "demo@example.com"

    logged_in = web._login_from_payload(
        {"email": "demo@example.com", "password": "password-123"}
    )
    assert logged_in["ok"] is True

    web._logout_from_cookie(f"{web.AUTH_COOKIE}={token}")
    assert web._auth_me_from_cookie(f"{web.AUTH_COOKIE}={token}")["authenticated"] is False


def test_web_pipeline_payload_runs_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    db_path = tmp_path / "data" / "web_demo.db"
    state = WebState()

    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "query": "Werkstudent KI",
            "limit": 2,
            "threshold": 0.5,
            "db_path": str(db_path),
            "reset_db": True,
            "llm_agents": False,
            "chroma": False,
        },
        state,
    )

    assert response["ok"] is True
    assert response["summary"]["jobs"] == 2
    assert response["summary"]["matches"] == 2
    assert response["jobs"][0]["title"]
    assert response["jobs"][0]["source_label"]
    assert response["jobs"][0]["score_components"]
    assert response["jobs"][0]["risk_level"] in {"low", "medium", "high"}
    assert response["applications"]
    assert db_path.exists()


def test_web_rejects_db_path_outside_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    with pytest.raises(ValueError, match="project data directory"):
        web._resolve_db_path(str(tmp_path.parent / "outside.db"))


def test_web_config_payload_uses_safe_db_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    out = web._config_payload()
    assert out["ok"] is True
    assert str(tmp_path / "data") in out["default_demo_db"]


def test_use_demo_profile_sets_current_profile() -> None:
    state = WebState()
    out = web._use_demo_profile(state)
    assert out["ok"] is True
    assert out["source"] == "demo"
    sess = state.session(None)
    assert sess.current_profile is not None
    assert sess.current_profile_source == "demo"
    assert sess.current_profile.name == out["profile"]["name"]


def test_pipeline_keeps_demo_profile_source_after_demo_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    db_path = tmp_path / "data" / "web_demo.db"
    state = WebState()
    web._use_demo_profile(state)

    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "threshold": 0.5,
            "db_path": str(db_path),
            "reset_db": True,
        },
        state,
    )

    assert response["profile"]["source"] == "demo"
    assert response["profile"]["from_cv"] is False


def test_web_draft_all_creates_drafts_for_low_score_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = WebState()

    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 5,
            "threshold": 0.5,
            "draft_all": True,
            "db_path": str(tmp_path / "data" / "draft_all.db"),
            "reset_db": True,
            "force_demo_profile": True,
        },
        state,
    )

    assert response["summary"]["jobs"] == 5
    assert response["summary"]["drafts"] == 5
    assert any((job["score"] or 0) < 0.5 for job in response["jobs"])


def test_generate_draft_creates_application_for_selected_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    db_path = tmp_path / "data" / "manual_draft.db"
    state = WebState()
    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "threshold": 0.99,
            "draft_all": False,
            "db_path": str(db_path),
            "reset_db": True,
            "force_demo_profile": True,
        },
        state,
    )
    job_id = response["jobs"][0]["id"]
    assert response["summary"]["drafts"] == 0

    out = web._generate_draft_from_payload({"db_path": str(db_path), "job_id": job_id}, state)

    assert out["ok"] is True
    assert out["application"]["job_id"] == job_id
    assert out["applications"][0]["job_id"] == job_id

    store = Store(db_path)
    try:
        assert store.get_application(job_id) is not None
        assert store.get_status(job_id).status == "draft"  # type: ignore[union-attr]
    finally:
        store.close()


def test_state_payload_rebuilds_jobs_and_applications_from_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    db_path = tmp_path / "data" / "state_rebuild.db"
    state = WebState()
    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "draft_all": True,
            "db_path": str(db_path),
            "reset_db": True,
            "force_demo_profile": True,
        },
        state,
    )
    job_id = response["jobs"][0]["id"]

    with state.lock:
        state.session(None).last_result = None

    out = web._state_payload(state)

    assert out["ok"] is True
    assert out["jobs"][0]["id"] == job_id
    assert out["applications"][0]["job_id"] == job_id
    assert out["summary"]["drafts"] == 1


def test_report_and_interview_prep_fall_back_to_current_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = WebState()
    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "threshold": 0.99,
            "db_path": str(tmp_path / "data" / "first.db"),
            "reset_db": True,
            "force_demo_profile": True,
        },
        state,
    )
    job_id = response["jobs"][0]["id"]
    empty_db = tmp_path / "data" / "empty.db"

    prep = web._interview_prep_payload({"db_path": [str(empty_db)], "job_id": [job_id]}, state)
    report = web._export_report_from_payload({"db_path": str(empty_db), "job_id": job_id}, state)

    assert prep["ok"] is True
    assert prep["prep"]["job_id"] == job_id
    assert report["ok"] is True
    assert report["download"].startswith("/api/download?")


def test_update_status_persists_application_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    db_path = tmp_path / "data" / "web_demo.db"
    state = WebState()

    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "threshold": 0.5,
            "db_path": str(db_path),
            "reset_db": True,
        },
        state,
    )
    job_id = response["jobs"][0]["id"]

    out = web._update_status_from_payload(
        {
            "db_path": str(db_path),
            "job_id": job_id,
            "status": "submitted",
            "notes": "Heute versendet",
        },
        state,
    )

    assert out["ok"] is True
    assert out["status"]["status"] == "submitted"
    assert out["status"]["notes"] == "Heute versendet"
    assert out["applications"][0]["status"] == "submitted"

    store = Store(db_path)
    try:
        persisted = store.get_status(job_id)
    finally:
        store.close()
    assert persisted is not None
    assert persisted.status == "submitted"
    assert persisted.submitted_at is not None


def test_send_application_email_dry_run_records_note_without_submitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_dry_run", True)
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_demo_recipient", "demo@example.com")
    monkeypatch.setattr("job_agent.tools.email_delivery.settings.email_from", "sender@example.com")
    db_path = tmp_path / "data" / "web_demo.db"
    state = WebState()

    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "threshold": 0.5,
            "db_path": str(db_path),
            "reset_db": True,
        },
        state,
    )
    job_id = response["jobs"][0]["id"]

    out = web._send_application_email_from_payload(
        {
            "db_path": str(db_path),
            "job_id": job_id,
        },
        state,
    )

    assert out["ok"] is True
    assert out["email"]["dry_run"] is True
    assert out["status"]["status"] == "draft"
    assert "Dry-run vorbereitet" in out["status"]["notes"]


def test_send_application_email_can_retry_after_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    db_path = tmp_path / "data" / "retry_after_dry_run.db"
    state = WebState()

    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "threshold": 0.5,
            "draft_all": True,
            "db_path": str(db_path),
            "reset_db": True,
            "force_demo_profile": True,
        },
        state,
    )
    job_id = response["jobs"][0]["id"]

    monkeypatch.setattr(web.settings, "email_dry_run", True)
    monkeypatch.setattr(web.settings, "email_demo_recipient", "demo@example.com")
    monkeypatch.setattr(web.settings, "email_from", "sender@example.com")
    first = web._send_application_email_from_payload({"db_path": str(db_path), "job_id": job_id}, state)
    assert first["ok"] is True
    assert first["email"]["dry_run"] is True

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self, context=None) -> None:  # type: ignore[no-untyped-def]
            return None

        def login(self, user: str, password: str) -> None:
            self.login_user = user
            self.login_password = password

        def noop(self) -> None:
            return None

        def send_message(self, message) -> None:  # type: ignore[no-untyped-def]
            self.message = message

    monkeypatch.setattr(web.settings, "email_dry_run", False)
    monkeypatch.setattr(web.settings, "email_smtp_host", "smtp.example.com")
    monkeypatch.setattr(web.settings, "email_smtp_port", 587)
    monkeypatch.setattr(web.settings, "email_use_tls", True)
    monkeypatch.setattr(web.settings, "email_smtp_user", "sender@example.com")
    monkeypatch.setattr(web.settings, "email_smtp_password", "app-password")
    monkeypatch.setattr(web.settings, "email_review_recipient", "review@example.com")
    monkeypatch.setattr("job_agent.tools.email_delivery.validate_public_host", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr("job_agent.tools.email_delivery.smtplib.SMTP", FakeSMTP)

    second = web._send_application_email_from_payload(
        {
            "db_path": str(db_path),
            "job_id": job_id,
            "confirm_real_send": True,
        },
        state,
    )

    assert second["ok"] is True
    assert second["email"]["sent"] is True
    assert second["email"]["dry_run"] is False
    assert second["status"]["status"] == "submitted"

    store = Store(db_path)
    try:
        entry = store.email_outbox_entry(second["email"]["idempotency_key"])
        assert entry is not None
        assert entry["state"] == "sent"
        status = store.get_status(job_id)
        assert status is not None
        assert status.status == "submitted"
    finally:
        store.close()


def test_sync_email_status_endpoint_returns_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    db_path = tmp_path / "data" / "web_demo.db"
    state = WebState()

    response = _run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "threshold": 0.5,
            "db_path": str(db_path),
            "reset_db": True,
        },
        state,
    )
    job_id = response["jobs"][0]["id"]

    def fake_sync(store, limit=None, account=None):  # type: ignore[no-untyped-def]
        return {
            "ok": True,
            "dry_run": True,
            "updates": [{"job_id": job_id, "stage": "interview"}],
        }

    monkeypatch.setattr("job_agent.tools.email_sync.sync_email_statuses", fake_sync)

    out = web._sync_email_status_from_payload(
        {
            "db_path": str(db_path),
        },
        state,
    )

    assert out["ok"] is True
    assert out["sync"]["updates"][0]["stage"] == "interview"
    assert out["applications"]


def test_update_status_rejects_unknown_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    with pytest.raises(ValueError, match="Unknown status"):
        web._update_status_from_payload(
            {"db_path": str(tmp_path / "data" / "x.db"), "job_id": "j1", "status": "done"},
            WebState(),
        )
