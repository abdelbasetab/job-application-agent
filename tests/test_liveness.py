"""Liveness classification (offline, injected fetch) + store + web endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent import web
from job_agent.memory.store import Store
from job_agent.schemas import LivenessResult
from job_agent.tools.liveness import FetchResult, check_liveness


def _fetch(status: int, body: str = "", final: str = "https://example.de/job"):
    def fetch(url: str, timeout: float) -> FetchResult:
        return status, final, body

    return fetch


def test_check_liveness_http_404_is_expired() -> None:
    result = check_liveness("https://example.de/job", fetch=_fetch(404))
    assert result.status == "expired"
    assert result.checked_via == "http"
    assert result.confidence >= 0.8


def test_check_liveness_expired_text_in_body() -> None:
    body = "<html>Diese Stelle ist leider nicht mehr verfügbar.</html>"
    result = check_liveness("https://example.de/job", fetch=_fetch(200, body))
    assert result.status == "expired"


def test_check_liveness_live_content() -> None:
    body = "<html>Werkstudent KI (m/w/d) — jetzt bewerben!</html>"
    result = check_liveness("https://example.de/job", fetch=_fetch(200, body))
    assert result.status == "live"
    assert 0.0 < result.confidence <= 1.0


def test_check_liveness_blocked_is_unknown() -> None:
    result = check_liveness("https://example.de/job", fetch=_fetch(403))
    assert result.status == "unknown"


def test_check_liveness_fetch_error_is_unknown_not_raise() -> None:
    def boom(url: str, timeout: float) -> FetchResult:
        raise TimeoutError("connect timeout")

    result = check_liveness("https://example.de/job", fetch=boom)
    assert result.status == "unknown"
    assert "unsicher" in result.reason.lower()


def test_store_liveness_roundtrip(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    try:
        store.save_liveness(
            "job-1", LivenessResult(url="https://x.de", status="live", confidence=0.7, reason="ok")
        )
        got = store.get_liveness("job-1")
        assert got is not None
        assert got.status == "live"
        assert store.all_liveness()["job-1"].status == "live"
    finally:
        store.close()


def test_web_check_liveness_endpoint_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = web.WebState()
    resp = web._run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "draft_all": True,
            "reset_db": True,
            "db_path": str(tmp_path / "data" / "live.db"),
        },
        state,
    )
    job_id = resp["jobs"][0]["id"]
    fixed = LivenessResult(url="https://x.de", status="expired", confidence=0.9, reason="weg")
    monkeypatch.setattr(
        "job_agent.tools.liveness.check_liveness", lambda url, deep=False: fixed
    )

    out = web._check_liveness_from_payload({"db_path": resp["db_path"], "job_id": job_id}, state)
    assert out["ok"] is True
    assert out["liveness"]["status"] == "expired"

    # Persisted and surfaced in the per-session state payload.
    state_payload = web._state_payload(state)
    job = next(j for j in state_payload["jobs"] if j["id"] == job_id)
    assert job["liveness"]["status"] == "expired"
