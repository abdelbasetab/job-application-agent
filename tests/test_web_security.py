"""Multi-user isolation, CSRF, and auth-throttling for the web layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_agent import web
from job_agent.memory.auth_store import AuthStore
from job_agent.web import WebState, _run_pipeline_from_payload


def _user(uid: int) -> dict[str, Any]:
    return {"id": uid, "email": f"user{uid}@example.com", "created_at": "2026-01-01T00:00:00"}


def _use_local_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")


def test_pipeline_data_is_isolated_per_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_local_data(monkeypatch, tmp_path)
    state = WebState()

    ra = _run_pipeline_from_payload(
        {
            "demo": True,
            "force_demo_profile": True,
            "limit": 1,
            "draft_all": True,
            "reset_db": True,
        },
        state,
        user=_user(1),
    )
    rb = _run_pipeline_from_payload(
        {
            "demo": True,
            "force_demo_profile": True,
            "limit": 3,
            "draft_all": True,
            "reset_db": True,
        },
        state,
        user=_user(2),
    )

    a_path = ra["db_path"].replace("\\", "/")
    b_path = rb["db_path"].replace("\\", "/")
    assert "/users/1/" in a_path
    assert "/users/2/" in b_path
    assert a_path != b_path
    assert Path(ra["db_path"]).exists()
    assert Path(rb["db_path"]).exists()

    # Separate stores: B's three drafts never leak into A's single-draft store.
    a_apps = web._load_applications(ra["db_path"], web._user_data_dir(1))
    b_apps = web._load_applications(rb["db_path"], web._user_data_dir(2))
    assert len(a_apps) == 1
    assert len(b_apps) == 3


def test_user_cannot_reach_another_users_db_by_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_local_data(monkeypatch, tmp_path)
    state = WebState()
    _run_pipeline_from_payload(
        {
            "demo": True,
            "force_demo_profile": True,
            "limit": 1,
            "draft_all": True,
            "reset_db": True,
        },
        state,
        user=_user(1),
    )
    rb = _run_pipeline_from_payload(
        {
            "demo": True,
            "force_demo_profile": True,
            "limit": 3,
            "draft_all": True,
            "reset_db": True,
        },
        state,
        user=_user(2),
    )

    # User 1 explicitly points at user 2's DB file; the path is re-based into
    # user 1's own directory, so the read can never return user 2's data.
    leaked = web._load_applications(rb["db_path"], web._user_data_dir(1))
    assert len(leaked) == 1


def test_authenticated_pipeline_never_selects_demo_profile_implicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_local_data(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="bewusst"):
        _run_pipeline_from_payload(
            {"demo": True, "limit": 1}, WebState(), user=_user(9)
        )


def test_resolve_db_path_confines_to_user_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_local_data(monkeypatch, tmp_path)
    root = (tmp_path / "data" / "users" / "7").resolve()
    root.mkdir(parents=True)

    rebased = web._resolve_db_path("../../../etc/evil.db", root)
    assert rebased.parent == root
    assert rebased.name == "evil.db"

    confined = web._resolve_db_path("./data/demo_job_agent.db", root)
    assert confined.parent == root


def test_resolve_db_path_without_root_rejects_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_local_data(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="project data directory"):
        web._resolve_db_path(str(tmp_path.parent / "outside.db"))


def test_login_is_rate_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "AUTH_DB_PATH", tmp_path / "auth.db")
    monkeypatch.setattr(web.settings, "web_allow_registration", True)
    web._register_from_payload({"email": "rl@example.com", "password": "password-123"}, "9.9.9.9")

    throttled = 0
    for _ in range(web._LOGIN_MAX_ATTEMPTS + 3):
        try:
            web._login_from_payload({"email": "rl@example.com", "password": "nope"}, "9.9.9.9")
        except ValueError as exc:
            if "Zu viele" in str(exc):
                throttled += 1
    assert throttled >= 1


def test_csrf_token_valid_is_strict() -> None:
    token = web._new_csrf_token()
    cookie = f"other=x; {web.CSRF_COOKIE}={token}"
    assert web._csrf_token_valid(cookie, token) is True
    assert web._csrf_token_valid(cookie, "wrong") is False
    assert web._csrf_token_valid("", token) is False
    assert web._csrf_token_valid(cookie, "") is False


def test_session_cookie_is_httponly_csrf_cookie_is_readable() -> None:
    session = web._session_cookie("tok")
    csrf = web._csrf_cookie("tok")
    assert "HttpOnly" in session
    assert "SameSite=Lax" in session
    assert "HttpOnly" not in csrf  # the SPA must read it to echo it back
    assert "SameSite=Lax" in csrf


def test_secure_cookie_flag_follows_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web.settings, "web_secure_cookies", True)
    assert "Secure" in web._session_cookie("tok")
    monkeypatch.setattr(web.settings, "web_secure_cookies", False)
    assert "Secure" not in web._session_cookie("tok")


def test_account_delete_removes_auth_data_and_memory_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_local_data(monkeypatch, tmp_path)
    monkeypatch.setattr(web, "AUTH_DB_PATH", tmp_path / "data" / "auth.db")
    auth = AuthStore(web.AUTH_DB_PATH)
    user = auth.create_user("delete@example.com", "password-123")
    auth.close()
    state = WebState()
    user_root = web._user_data_dir(user["id"])
    (user_root / "personal.txt").write_text("private", encoding="utf-8")
    state.session(user)

    result = web._delete_account_from_payload(
        {"confirm": "DELETE", "password": "password-123"}, state, user
    )

    assert result["ok"] is True
    assert result["cleanup_pending"] is False
    assert not user_root.exists()
    reopened = AuthStore(web.AUTH_DB_PATH)
    try:
        assert reopened.authenticate("delete@example.com", "password-123") is None
    finally:
        reopened.close()
    assert user["id"] not in state._users
    assert not web._account_deletion_in_progress(user["id"])


def test_account_delete_refuses_while_pipeline_is_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_local_data(monkeypatch, tmp_path)
    monkeypatch.setattr(web, "AUTH_DB_PATH", tmp_path / "data" / "auth.db")
    auth = AuthStore(web.AUTH_DB_PATH)
    user = auth.create_user("busy@example.com", "password-123")
    auth.close()
    with web._PROGRESS_LOCK:
        web._ACTIVE_PIPELINE_OWNERS.add(user["id"])
    try:
        with pytest.raises(ValueError, match="Pipeline"):
            web._delete_account_from_payload(
                {"confirm": "DELETE", "password": "password-123"}, WebState(), user
            )
    finally:
        with web._PROGRESS_LOCK:
            web._ACTIVE_PIPELINE_OWNERS.discard(user["id"])

    reopened = AuthStore(web.AUTH_DB_PATH)
    try:
        assert reopened.authenticate("busy@example.com", "password-123") is not None
    finally:
        reopened.close()
