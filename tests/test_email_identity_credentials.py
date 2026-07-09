from __future__ import annotations

import sqlite3
from pathlib import Path

from job_agent.demo_profile import demo_profile
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
        update={"email": "adessadmax.mustermann.app@gmail.comess1990@gmail.com"}
    )

    payload = email_identity_payload(profile, user_email="max.mustermann.app@gmail.com")

    assert payload["profile_email"] == "max.mustermann.app@gmail.com"
    assert payload["candidate_email"] == "max.mustermann.app@gmail.com"


def test_account_from_mapping_repairs_concatenated_saved_email_with_fallback() -> None:
    account = account_from_mapping(
        {
            "email_address": "adessadmax.mustermann.app@gmail.comess1990@gmail.com",
            "email_from": "adessadmax.mustermann.app@gmail.comess1990@gmail.com",
            "smtp_user": "adessadmax.mustermann.app@gmail.comess1990@gmail.com",
            "imap_user": "adessadmax.mustermann.app@gmail.comess1990@gmail.com",
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
