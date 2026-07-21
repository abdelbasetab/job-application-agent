"""Local encrypted credential storage for per-user integrations.

This is a local-first foundation, not a SaaS-grade secret manager. It keeps
secrets out of plain SQLite rows by encrypting them with a random key file that
stays on the same machine. A SaaS deployment should replace this module with a
KMS-backed implementation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

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
_KEY_LOCK = threading.Lock()
_MAX_CREDENTIAL_JSON_BYTES = 1_000_000


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
        if not service or len(service) > 100:
            raise ValueError("Credential service name is invalid.")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(encoded) > _MAX_CREDENTIAL_JSON_BYTES:
            raise ValueError("Credential payload is too large.")
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
        encrypted = str(row[0])
        data = _decrypt_json(encrypted, self._key)
        if not encrypted.startswith("v2.") and isinstance(data, dict):
            # Transparently rewrite the authenticated legacy format after the
            # first successful read. Legacy encryption remains read-only.
            self.save_json(service, data)
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
    with _KEY_LOCK:
        if path.exists():
            return _read_key(path)
        key = secrets.token_bytes(32)
        temp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with temp_path.open("x", encoding="ascii") as handle:
                handle.write(base64.urlsafe_b64encode(key).decode("ascii"))
                handle.flush()
                os.fsync(handle.fileno())
            _restrict_permissions(temp_path)
            os.replace(temp_path, path)
            _restrict_permissions(path)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        return key


def _read_key(path: Path) -> bytes:
    raw = path.read_text(encoding="ascii").strip()
    try:
        key = base64.urlsafe_b64decode(raw.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeError) as exc:
        raise ValueError("Credential key file is malformed.") from exc
    if len(key) != 32:
        raise ValueError("Credential key must contain exactly 32 bytes.")
    return key


def _restrict_permissions(path: Path) -> None:
    """Best-effort chmod 600 for the key file (no-op on Windows/odd FS)."""
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass


def _encrypt_json(payload: dict[str, Any], key: bytes) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    nonce = secrets.token_bytes(12)
    cipher = AESGCM(key).encrypt(nonce, raw, b"job-agent:credential:v2")
    return "v2." + ".".join(
        base64.urlsafe_b64encode(part).decode("ascii") for part in (nonce, cipher)
    )


def _decrypt_json(payload: str, key: bytes) -> Any:
    if payload.startswith("v2."):
        try:
            version, raw_nonce, raw_cipher = payload.split(".", 2)
            if version != "v2":
                raise ValueError
            nonce = base64.urlsafe_b64decode(raw_nonce.encode("ascii"))
            cipher = base64.urlsafe_b64decode(raw_cipher.encode("ascii"))
            if len(nonce) != 12:
                raise ValueError
            raw = AESGCM(key).decrypt(nonce, cipher, b"job-agent:credential:v2")
            return json.loads(raw.decode("utf-8"))
        except (binascii.Error, InvalidTag, UnicodeError, ValueError) as exc:
            raise ValueError("Credential payload failed integrity check.") from exc
    return _decrypt_legacy_json(payload, key)


def _decrypt_legacy_json(payload: str, key: bytes) -> Any:
    """Read the authenticated v1 format solely for in-place migration."""
    try:
        raw_nonce, raw_cipher, raw_mac = payload.split(".", 2)
        nonce = base64.urlsafe_b64decode(raw_nonce.encode("ascii"))
        cipher = base64.urlsafe_b64decode(raw_cipher.encode("ascii"))
        mac = base64.urlsafe_b64decode(raw_mac.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
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
