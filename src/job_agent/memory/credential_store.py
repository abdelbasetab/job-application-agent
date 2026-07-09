"""Local encrypted credential storage for per-user integrations.

This is a local-first foundation, not a SaaS-grade secret manager. It keeps
secrets out of plain SQLite rows by encrypting them with a random key file that
stays on the same machine. A SaaS deployment should replace this module with a
KMS-backed implementation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# `datetime.UTC` is 3.11+ — the timezone.utc spelling keeps the module
# importable on older interpreters (see memory/auth_store.py).
UTC = timezone.utc  # noqa: UP017

_MIGRATIONS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS credentials (
        service TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
]


class CredentialStore:
    def __init__(self, db_path: str | Path, key_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path = Path(key_path) if key_path else self.db_path.with_suffix(".key")
        self._key = _load_or_create_key(self.key_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._apply_migrations()

    def save_json(self, service: str, payload: dict[str, Any]) -> None:
        encrypted = _encrypt_json(payload, self._key)
        self._conn.execute(
            "INSERT OR REPLACE INTO credentials(service, payload, updated_at) VALUES (?, ?, ?)",
            (service, encrypted, datetime.now(UTC).isoformat()),
        )
        self._conn.commit()

    def load_json(self, service: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload FROM credentials WHERE service = ?", (service,)
        ).fetchone()
        if row is None:
            return None
        data = _decrypt_json(str(row[0]), self._key)
        return data if isinstance(data, dict) else None

    def delete(self, service: str) -> bool:
        cursor = self._conn.execute("DELETE FROM credentials WHERE service = ?", (service,))
        self._conn.commit()
        return bool(cursor.rowcount)

    def close(self) -> None:
        self._conn.close()

    def _apply_migrations(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for index in range(version, len(_MIGRATIONS)):
            self._conn.executescript(_MIGRATIONS[index])
            self._conn.execute(f"PRAGMA user_version = {index + 1}")
        self._conn.commit()


def _load_or_create_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raw = path.read_text(encoding="ascii").strip()
        return base64.urlsafe_b64decode(raw.encode("ascii"))
    key = secrets.token_bytes(32)
    path.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="ascii")
    _restrict_permissions(path)
    return key


def _restrict_permissions(path: Path) -> None:
    """Best-effort chmod 600 for the key file (no-op on Windows/odd FS)."""
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass


def _encrypt_json(payload: dict[str, Any], key: bytes) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    nonce = secrets.token_bytes(16)
    stream = _keystream(key, nonce, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream, strict=True))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return ".".join(
        base64.urlsafe_b64encode(part).decode("ascii") for part in (nonce, cipher, mac)
    )


def _decrypt_json(payload: str, key: bytes) -> Any:
    try:
        raw_nonce, raw_cipher, raw_mac = payload.split(".", 2)
        nonce = base64.urlsafe_b64decode(raw_nonce.encode("ascii"))
        cipher = base64.urlsafe_b64decode(raw_cipher.encode("ascii"))
        mac = base64.urlsafe_b64decode(raw_mac.encode("ascii"))
    except ValueError as exc:
        raise ValueError("Credential payload is malformed.") from exc
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Credential payload failed integrity check.")
    stream = _keystream(key, nonce, len(cipher))
    raw = bytes(a ^ b for a, b in zip(cipher, stream, strict=True))
    return json.loads(raw.decode("utf-8"))


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        counter_bytes = counter.to_bytes(8, "big")
        chunks.append(hashlib.sha256(key + nonce + counter_bytes).digest())
        counter += 1
    return b"".join(chunks)[:length]
