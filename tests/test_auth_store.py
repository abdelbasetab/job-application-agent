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
    with pytest.raises(ValueError, match="mindestens 12"):
        store.create_user("user@example.com", "short")
    store.close()


@pytest.mark.parametrize(
    "email",
    ["missing-at.example.com", "@example.com", "user@", "user@example", "a..b@example.com"],
)
def test_auth_store_rejects_malformed_email(tmp_path: Path, email: str) -> None:
    store = AuthStore(tmp_path / "auth.db")
    with pytest.raises(ValueError, match="gültige E-Mail"):
        store.create_user(email, "password-123")
    store.close()


def test_password_change_invalidates_sessions_and_delete_verifies_password(
    tmp_path: Path,
) -> None:
    store = AuthStore(tmp_path / "auth.db")
    user = store.create_user("user@example.com", "password-123")
    token = store.create_session(user["id"])

    store.change_password(user["id"], "password-123", "new-password-456")

    assert store.user_for_session(token) is None
    assert store.authenticate("user@example.com", "password-123") is None
    assert store.authenticate("user@example.com", "new-password-456") is not None
    with pytest.raises(ValueError, match="falsch"):
        store.delete_user(user["id"], "wrong-password")
    store.delete_user(user["id"], "new-password-456")
    assert store.authenticate("user@example.com", "new-password-456") is None
    store.close()


def test_auth_rejects_huge_password_without_hashing(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.db")
    store.create_user("user@example.com", "password-123")
    assert store.authenticate("user@example.com", "x" * 100_000) is None
    with pytest.raises(ValueError, match="hoechstens 256"):
        store.create_user("other@example.com", "x" * 257)
    store.close()
