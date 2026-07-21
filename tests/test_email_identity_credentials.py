from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from job_agent.demo_profile import demo_profile
from job_agent.memory import credential_store
from job_agent.memory.credential_store import CredentialStore
from job_agent.tools.email_account import account_from_mapping, email_identity_payload


def test_email_identity_warns_when_profile_and_imap_differ() -> None:
    profile = demo_profile().model_copy(update={"email": "cv@example.de"})
    account = account_from_mapping(
        {
            "email_address": "sender@example.de",
            "email_from": "sender@example.de",
            "smtp_host": "smtp.example.de",
            "smtp_user": "sender@example.de",
            "smtp_password": "secret",
            "imap_host": "imap.example.de",
            "imap_user": "inbox@example.de",
            "imap_password": "secret",
        }
    )

    payload = email_identity_payload(profile, user_email="login@example.de", account=account)

    assert payload["profile_email"] == "cv@example.de"
    assert payload["smtp_ready"] is True
    assert payload["imap_ready"] is True
    assert payload["warnings"]


def test_email_identity_prefers_login_inside_concatenated_cv_email() -> None:
    profile = demo_profile().model_copy(
        update={"email": "prefixmax.mustermann.app@gmail.comsuffix"}
    )

    payload = email_identity_payload(profile, user_email="max.mustermann.app@gmail.com")

    assert payload["profile_email"] == "max.mustermann.app@gmail.com"
    assert payload["candidate_email"] == "max.mustermann.app@gmail.com"


def test_account_from_mapping_repairs_concatenated_saved_email_with_fallback() -> None:
    account = account_from_mapping(
        {
            "email_address": "prefixmax.mustermann.app@gmail.comsuffix",
            "email_from": "prefixmax.mustermann.app@gmail.comsuffix",
            "smtp_user": "prefixmax.mustermann.app@gmail.comsuffix",
            "imap_user": "prefixmax.mustermann.app@gmail.comsuffix",
        },
        fallback_email="max.mustermann.app@gmail.com",
    )

    assert account.email_address == "max.mustermann.app@gmail.com"
    assert account.email_from == "max.mustermann.app@gmail.com"
    assert account.smtp_user == "max.mustermann.app@gmail.com"
    assert account.imap_user == "max.mustermann.app@gmail.com"


def test_credential_store_roundtrip_does_not_store_plaintext(tmp_path: Path) -> None:
    db_path = tmp_path / "credentials.db"
    store = CredentialStore(db_path)
    try:
        store.save_json("email", {"smtp_password": "app-password", "smtp_user": "me@example.de"})
        loaded = store.load_json("email")
    finally:
        store.close()

    assert loaded == {"smtp_password": "app-password", "smtp_user": "me@example.de"}
    conn = sqlite3.connect(db_path)
    try:
        raw = conn.execute("SELECT payload FROM credentials WHERE service = 'email'").fetchone()[0]
    finally:
        conn.close()
    assert "app-password" not in str(raw)
    assert str(raw).startswith("v2.")


def test_credential_store_rejects_tampering(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials.db")
    try:
        store.save_json("email", {"secret": "value"})
        row = store._conn.execute(
            "SELECT payload FROM credentials WHERE service = 'email'"
        ).fetchone()
        payload = str(row[0])
        replacement = "A" if payload[-1] != "A" else "B"
        store._conn.execute(
            "UPDATE credentials SET payload = ? WHERE service = 'email'",
            (payload[:-1] + replacement,),
        )
        store._conn.commit()
        with pytest.raises(ValueError, match="integrity"):
            store.load_json("email")
    finally:
        store.close()


def test_credential_store_migrates_legacy_ciphertext(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials.db")
    try:
        raw = json.dumps({"secret": "legacy"}, sort_keys=True).encode()
        nonce = b"legacy-nonce-123"
        stream = credential_store._keystream(store._key, nonce, len(raw))
        cipher = bytes(a ^ b for a, b in zip(raw, stream, strict=True))
        mac = hmac.new(store._key, nonce + cipher, hashlib.sha256).digest()
        legacy = ".".join(
            base64.urlsafe_b64encode(part).decode() for part in (nonce, cipher, mac)
        )
        store._conn.execute(
            "INSERT INTO credentials(service, payload, updated_at) VALUES ('email', ?, 'now')",
            (legacy,),
        )
        store._conn.commit()

        assert store.load_json("email") == {"secret": "legacy"}
        migrated = store._conn.execute(
            "SELECT payload FROM credentials WHERE service = 'email'"
        ).fetchone()[0]
        assert str(migrated).startswith("v2.")
    finally:
        store.close()


def test_credential_key_creation_is_atomic_across_threads(tmp_path: Path) -> None:
    key_path = tmp_path / "credentials.key"
    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _index: credential_store._load_or_create_key(key_path), range(32)))

    assert len(set(keys)) == 1
    assert credential_store._read_key(key_path) == keys[0]


def test_credential_store_rejects_oversized_payload(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials.db")
    try:
        with pytest.raises(ValueError, match="too large"):
            store.save_json("email", {"secret": "x" * 1_000_001})
    finally:
        store.close()
