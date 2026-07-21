from __future__ import annotations

from datetime import date

import pytest

from job_agent.schemas import GeneratedApplication, JobPosting
from job_agent.tools import email_delivery
from job_agent.tools.email_account import account_from_mapping


def _job() -> JobPosting:
    return JobPosting(
        id="job-email-1",
        source="manual",
        source_id="job-email-1",
        url="https://example.com/jobs/1",
        title="Werkstudent KI",
        company="Example GmbH",
        location="Essen",
        description="Python and RAG role.",
        requirements=["python"],
    )


def _application() -> GeneratedApplication:
    return GeneratedApplication(
        job_id="job-email-1",
        cover_letter_md="Sehr geehrte Damen und Herren,\n\nich bewerbe mich.",
        generated_at=date.today(),
    )


def test_email_delivery_dry_run_does_not_send(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(email_delivery.settings, "email_dry_run", True)
    monkeypatch.setattr(email_delivery.settings, "email_demo_recipient", "demo@example.com")
    monkeypatch.setattr(email_delivery.settings, "email_from", "sender@example.com")

    result = email_delivery.send_application_email(_job(), _application())

    assert result["sent"] is False
    assert result["dry_run"] is True
    assert result["recipient"] == "demo@example.com"
    assert result["subject"] == "Bewerbung: Werkstudent KI - Example GmbH"
    assert "ich bewerbe mich" in result["body_preview"]
    assert "Job Application Agent" not in result["body_preview"]
    assert "Quelle der Stelle" not in result["body_preview"]
    assert result["message_id"]


def test_email_delivery_uses_smtp_when_enabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sent: dict = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:  # type: ignore[no-untyped-def]
            return None

        def starttls(self, context=None) -> None:  # type: ignore[no-untyped-def]
            sent["tls"] = True

        def login(self, user: str, password: str) -> None:
            sent["login"] = (user, password)

        def send_message(self, message) -> None:  # type: ignore[no-untyped-def]
            sent["to"] = message["To"]
            sent["subject"] = message["Subject"]

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_delivery, "validate_public_host", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr(email_delivery.settings, "email_dry_run", False)
    monkeypatch.setattr(email_delivery.settings, "email_smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_delivery.settings, "email_smtp_port", 587)
    monkeypatch.setattr(email_delivery.settings, "email_use_tls", True)
    monkeypatch.setattr(email_delivery.settings, "email_smtp_user", "sender@example.com")
    monkeypatch.setattr(email_delivery.settings, "email_smtp_password", "app-password")
    monkeypatch.setattr(email_delivery.settings, "email_from", "sender@example.com")

    result = email_delivery.send_application_email(
        _job(),
        _application(),
        recipient="hr@example.com",
    )

    assert result["sent"] is True
    assert result["dry_run"] is False
    assert sent["host"] == "smtp.example.com"
    assert sent["tls"] is True
    assert sent["login"] == ("sender@example.com", "app-password")
    assert sent["to"] == "hr@example.com"


def test_email_delivery_rejects_unencrypted_smtp(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(email_delivery, "validate_public_host", lambda *_args, **_kwargs: "ok")
    account = account_from_mapping(
        {
            "email_address": "sender@example.com",
            "smtp_host": "smtp.example.com",
            "smtp_user": "sender@example.com",
            "smtp_password": "app-password",
            "use_tls": False,
            "dry_run": False,
        }
    )

    with pytest.raises(ValueError, match="ohne TLS"):
        email_delivery.send_application_email(
            _job(), _application(), recipient="hr@example.com", account=account
        )


def test_email_delivery_uses_implicit_tls_on_port_465(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: dict[str, object] = {}

    class FakeSMTPSSL:
        def __init__(self, host: str, port: int, timeout: int, context=None) -> None:  # type: ignore[no-untyped-def]
            seen.update({"host": host, "port": port, "timeout": timeout})

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            seen["login"] = (user, password)

        def send_message(self, _message: object) -> None:
            seen["sent"] = True

    monkeypatch.setattr(email_delivery.smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setattr(email_delivery, "validate_public_host", lambda *_args, **_kwargs: "ok")
    account = account_from_mapping(
        {
            "email_address": "sender@example.com",
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_user": "sender@example.com",
            "smtp_password": "app-password",
            "use_tls": True,
            "dry_run": False,
        }
    )

    result = email_delivery.send_application_email(
        _job(), _application(), recipient="hr@example.com", account=account
    )

    assert result["sent"] is True
    assert seen["port"] == 465
