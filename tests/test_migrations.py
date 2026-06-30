"""Schema-migration and session-hygiene coverage for the SQLite stores."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from job_agent.memory.auth_store import _MIGRATIONS as AUTH_MIGRATIONS
from job_agent.memory.auth_store import AuthStore
from job_agent.memory.store import _MIGRATIONS as STORE_MIGRATIONS
from job_agent.memory.store import Store
from job_agent.schemas import JobPosting


def _job() -> JobPosting:
    return JobPosting(
        id="j-mig",
        source="manual",
        source_id="j-mig",
        url="https://example.com/jobs/mig",
        title="Werkstudent",
        company="Example GmbH",
        location="Essen",
        description="Role.",
        requirements=["python"],
    )


def _user_version(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def test_fresh_store_is_at_latest_version(tmp_path: Path) -> None:
    db = tmp_path / "store.db"
    store = Store(db)
    try:
        store.save_job(_job())
        assert store.get_job("j-mig") is not None
    finally:
        store.close()
    assert _user_version(db) == len(STORE_MIGRATIONS)


def test_legacy_store_db_upgrades_in_place(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE jobs(job_id TEXT PRIMARY KEY, payload TEXT NOT NULL);"
        "CREATE TABLE applications(job_id TEXT PRIMARY KEY, payload TEXT NOT NULL);"
        "CREATE TABLE status(job_id TEXT PRIMARY KEY, payload TEXT NOT NULL);"
    )
    conn.commit()
    conn.close()
    assert _user_version(db) == 0

    store = Store(db)
    try:
        store.save_job(_job())
        assert store.get_job("j-mig") is not None
    finally:
        store.close()
    assert _user_version(db) == len(STORE_MIGRATIONS)


def test_fresh_auth_store_has_session_index(tmp_path: Path) -> None:
    db = tmp_path / "auth.db"
    store = AuthStore(db)
    user = store.create_user("m@example.com", "password-123")
    token = store.create_session(user["id"])
    assert store.user_for_session(token) is not None
    store.close()

    assert _user_version(db) == len(AUTH_MIGRATIONS)
    conn = sqlite3.connect(db)
    try:
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sessions_user'"
        ).fetchone()
    finally:
        conn.close()
    assert idx is not None


def test_purge_expired_sessions_removes_stale_tokens(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.db")
    try:
        user = store.create_user("p@example.com", "password-123")
        token = store.create_session(user["id"])
        store._conn.execute("UPDATE sessions SET expires_at = ?", ("2000-01-01T00:00:00+00:00",))
        store._conn.commit()

        assert store.purge_expired_sessions() == 1
        assert store.user_for_session(token) is None
    finally:
        store.close()
