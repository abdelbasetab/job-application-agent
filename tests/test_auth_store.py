from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.memory.auth_store import AuthStore


def test_auth_store_register_login_session_logout(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.db")
    user = store.create_user("User@Example.com", "password-123")

    assert user["email"] == "user@example.com"
    assert store.authenticate("user@example.com", "wrong") is None
    authed = store.authenticate("user@example.com", "password-123")
    assert authed is not None
    assert authed["id"] == user["id"]

    token = store.create_session(user["id"])
    assert store.user_for_session(token)["email"] == "user@example.com"  # type: ignore[index]
    store.delete_session(token)
    assert store.user_for_session(token) is None
    store.close()


def test_auth_store_rejects_short_password(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.db")
    with pytest.raises(ValueError, match="mindestens 8"):
        store.create_user("user@example.com", "short")
    store.close()
