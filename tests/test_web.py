from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import web
from job_agent.memory.store import Store
from job_agent.web import WebState, _run_pipeline_from_payload


def test_web_auth_register_login_me_logout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "AUTH_DB_PATH", tmp_path / "auth.db")

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

    def fake_sync(store, limit=None):  # type: ignore[no-untyped-def]
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
