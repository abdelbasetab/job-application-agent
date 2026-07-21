from __future__ import annotations

import imaplib
import smtplib
from typing import Any

from job_agent.tools import email_connection
from job_agent.tools.email_account import account_from_mapping


def test_email_connection_checks_smtp_and_imap(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    smtp_seen: dict[str, Any] = {}
    imap_seen: dict[str, Any] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            smtp_seen.update({"host": host, "port": port, "timeout": timeout})

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ehlo(self) -> tuple[int, bytes]:
            return 250, b"ok"

        def starttls(self, context=None) -> tuple[int, bytes]:  # type: ignore[no-untyped-def]
            smtp_seen["tls"] = True
            return 220, b"ready"

        def login(self, user: str, password: str) -> tuple[int, bytes]:
            smtp_seen.update({"user": user, "password": password})
            return 235, b"auth ok"

        def noop(self) -> tuple[int, bytes]:
            return 250, b"ok"

    class FakeIMAP:
        def __init__(
            self, host: str, port: int, ssl_context=None, timeout: float = 15.0
        ) -> None:  # type: ignore[no-untyped-def]
            imap_seen.update({"host": host, "port": port, "timeout": timeout})

        def __enter__(self) -> FakeIMAP:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
            imap_seen.update({"user": user, "password": password})
            return "OK", [b"auth ok"]

        def select(self, folder: str, readonly: bool = False) -> tuple[str, list[bytes]]:
            imap_seen.update({"folder": folder, "readonly": readonly})
            return "OK", [b"1"]

    monkeypatch.setattr(email_connection.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_connection.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(email_connection, "validate_public_host", lambda *_args, **_kwargs: "ok")
    account = account_from_mapping(
        {
            "email_address": "me@example.de",
            "smtp_host": "smtp.example.de",
            "smtp_port": 587,
            "smtp_user": "me@example.de",
            "smtp_password": "smtp-secret",
            "imap_host": "imap.example.de",
            "imap_port": 993,
            "imap_user": "me@example.de",
            "imap_password": "imap-secret",
            "imap_folder": "INBOX",
        }
    )

    result = email_connection.test_email_connections(account, timeout=4)

    assert result["smtp"]["ok"] is True
    assert result["imap"]["ok"] is True
    assert smtp_seen["password"] == "smtp-secret"
    assert imap_seen["readonly"] is True
    assert "secret" not in str(result)


def test_gmail_app_password_spaces_are_removed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    smtp_seen: dict[str, Any] = {}
    imap_seen: dict[str, Any] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            smtp_seen.update({"host": host, "port": port, "timeout": timeout})

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ehlo(self) -> tuple[int, bytes]:
            return 250, b"ok"

        def starttls(self, context=None) -> tuple[int, bytes]:  # type: ignore[no-untyped-def]
            return 220, b"ready"

        def login(self, user: str, password: str) -> tuple[int, bytes]:
            smtp_seen.update({"user": user, "password": password})
            return 235, b"auth ok"

        def noop(self) -> tuple[int, bytes]:
            return 250, b"ok"

    class FakeIMAP:
        def __init__(
            self, host: str, port: int, ssl_context=None, timeout: float = 15.0
        ) -> None:  # type: ignore[no-untyped-def]
            imap_seen.update({"host": host, "port": port, "timeout": timeout})

        def __enter__(self) -> FakeIMAP:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
            imap_seen.update({"user": user, "password": password})
            return "OK", [b"auth ok"]

        def select(self, folder: str, readonly: bool = False) -> tuple[str, list[bytes]]:
            return "OK", [b"1"]

    monkeypatch.setattr(email_connection.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_connection.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(email_connection, "validate_public_host", lambda *_args, **_kwargs: "ok")
    account = account_from_mapping(
        {
            "email_address": "max.mustermann.app@gmail.com",
            "smtp_host": "smtp.gmail.com",
            "smtp_user": "max.mustermann.app@gmail.com",
            "smtp_password": "abcd efgh ijkl mnop",
            "imap_host": "imap.gmail.com",
            "imap_user": "max.mustermann.app@gmail.com",
            "imap_password": "abcd efgh ijkl mnop",
        }
    )

    result = email_connection.test_email_connections(account)

    assert result["smtp"]["ok"] is True
    assert result["imap"]["ok"] is True
    assert smtp_seen["password"] == "abcdefghijklmnop"
    assert imap_seen["password"] == "abcdefghijklmnop"


def test_gmail_auth_failure_has_actionable_message(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            pass

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ehlo(self) -> tuple[int, bytes]:
            return 250, b"ok"

        def starttls(self, context=None) -> tuple[int, bytes]:  # type: ignore[no-untyped-def]
            return 220, b"ready"

        def login(self, user: str, password: str) -> tuple[int, bytes]:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    class FakeIMAP:
        def __init__(
            self, host: str, port: int, ssl_context=None, timeout: float = 15.0
        ) -> None:  # type: ignore[no-untyped-def]
            pass

        def __enter__(self) -> FakeIMAP:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
            raise imaplib.IMAP4.error("bad credentials")

    monkeypatch.setattr(email_connection.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_connection.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(email_connection, "validate_public_host", lambda *_args, **_kwargs: "ok")
    account = account_from_mapping(
        {
            "email_address": "max.mustermann.app@gmail.com",
            "smtp_host": "smtp.gmail.com",
            "smtp_user": "max.mustermann.app@gmail.com",
            "smtp_password": "wrong",
            "imap_host": "imap.gmail.com",
            "imap_user": "max.mustermann.app@gmail.com",
            "imap_password": "wrong",
        }
    )

    result = email_connection.test_email_connections(account)

    assert result["smtp"]["ok"] is False
    assert "kein normales Google-Passwort" in result["smtp"]["message"]
    assert "App-Passwort ohne Leerzeichen" in result["imap"]["message"]


def test_email_connection_missing_credentials_is_safe() -> None:
    account = account_from_mapping({"email_address": "me@example.de"})

    result = email_connection.test_email_connections(account)

    assert result["smtp"]["ok"] is False
    assert result["smtp"]["configured"] is False
    assert result["imap"]["ok"] is False
    assert result["imap"]["configured"] is False


def test_email_connection_rejects_smtp_without_tls() -> None:
    account = account_from_mapping(
        {
            "email_address": "me@example.de",
            "smtp_host": "smtp.example.de",
            "smtp_user": "me@example.de",
            "smtp_password": "secret",
            "use_tls": False,
        }
    )

    result = email_connection.test_smtp_connection(account)

    assert result["ok"] is False
    assert "ohne TLS" in result["message"]
