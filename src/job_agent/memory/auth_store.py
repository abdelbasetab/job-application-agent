"""SQLite-backed users and sessions for the local web UI."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict

# `datetime.UTC` is 3.11+ — the timezone.utc spelling keeps the module
# importable on older interpreters (CI matrix, constrained environments).
UTC = timezone.utc  # noqa: UP017


class AuthUser(TypedDict):
    id: int
    email: str
    created_at: str


_ITERATIONS = 240_000
_SESSION_DAYS = 7
_LOCAL_PART_RE = re.compile(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64}", re.IGNORECASE)
_DOMAIN_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.IGNORECASE)

# Append-only migrations, tracked via PRAGMA user_version (see memory/store.py).
_MIGRATIONS: list[str] = [
    # v1 — users + sessions.
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """,
    # v2 — index for expiry sweeps and per-user session lookups.
    """
    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
    """,
]


def _apply_migrations(conn: sqlite3.Connection) -> int:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for index in range(version, len(_MIGRATIONS)):
        conn.executescript(_MIGRATIONS[index])
        conn.execute(f"PRAGMA user_version = {index + 1}")
    conn.commit()
    return len(_MIGRATIONS)


class AuthStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        _apply_migrations(self._conn)

    def create_user(self, email: str, password: str) -> AuthUser:
        normalized = _normalize_email(email)
        _validate_password(password)
        salt = secrets.token_hex(16)
        password_hash = _hash_password(password, salt)
        created_at = _now_iso()
        try:
            cursor = self._conn.execute(
                "INSERT INTO users(email, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                (normalized, password_hash, salt, created_at),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("Ein Benutzer mit dieser E-Mail existiert bereits.") from None
        if cursor.lastrowid is None:
            raise RuntimeError("User creation failed.")
        return {"id": cursor.lastrowid, "email": normalized, "created_at": created_at}

    def authenticate(self, email: str, password: str) -> AuthUser | None:
        if len(password) > 256:
            return None
        normalized = _normalize_email(email)
        row = self._conn.execute(
            "SELECT id, email, password_hash, salt, created_at FROM users WHERE email = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        expected = _hash_password(password, str(row[3]))
        if not hmac.compare_digest(expected, str(row[2])):
            return None
        return {"id": int(row[0]), "email": str(row[1]), "created_at": str(row[4])}

    def user_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        if len(current_password) > 256:
            raise ValueError("Das aktuelle Passwort ist falsch.")
        row = self._conn.execute(
            "SELECT password_hash, salt FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None or not hmac.compare_digest(
            _hash_password(current_password, str(row[1])), str(row[0])
        ):
            raise ValueError("Das aktuelle Passwort ist falsch.")
        _validate_password(new_password)
        salt = secrets.token_hex(16)
        with self._conn:
            self._conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (_hash_password(new_password, salt), salt, user_id),
            )
            self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def delete_user(self, user_id: int, password: str) -> None:
        if len(password) > 256:
            raise ValueError("Das Passwort ist falsch.")
        row = self._conn.execute(
            "SELECT password_hash, salt FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None or not hmac.compare_digest(
            _hash_password(password, str(row[1])), str(row[0])
        ):
            raise ValueError("Das Passwort ist falsch.")
        with self._conn:
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def create_session(self, user_id: int) -> str:
        self.purge_expired_sessions()
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        self._conn.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (
                _hash_token(token),
                user_id,
                now.isoformat(),
                (now + timedelta(days=_SESSION_DAYS)).isoformat(),
            ),
        )
        self._conn.commit()
        return token

    def purge_expired_sessions(self) -> int:
        """Delete sessions past their expiry. Returns the number removed."""
        cursor = self._conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?", (_now_iso(),)
        )
        self._conn.commit()
        return cursor.rowcount or 0

    def user_for_session(self, token: str | None) -> AuthUser | None:
        if not token:
            return None
        now = _now_iso()
        row = self._conn.execute(
            """
            SELECT users.id, users.email, users.created_at, sessions.expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
            """,
            (_hash_token(token),),
        ).fetchone()
        if row is None:
            return None
        if str(row[3]) <= now:
            self.delete_session(token)
            return None
        return {"id": int(row[0]), "email": str(row[1]), "created_at": str(row[2])}

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > 254 or normalized.count("@") != 1:
        raise ValueError("Bitte eine gültige E-Mail-Adresse eingeben.")
    local, domain = normalized.rsplit("@", 1)
    labels = domain.split(".")
    if (
        not _LOCAL_PART_RE.fullmatch(local)
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or len(labels) < 2
        or any(not _DOMAIN_LABEL_RE.fullmatch(label) for label in labels)
        or len(labels[-1]) < 2
    ):
        raise ValueError("Bitte eine gültige E-Mail-Adresse eingeben.")
    return normalized


def _validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Das Passwort muss mindestens 12 Zeichen haben.")
    if len(password) > 256:
        raise ValueError("Das Passwort darf hoechstens 256 Zeichen haben.")


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _ITERATIONS,
    )
    return digest.hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
