from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from job_agent import web
from job_agent.tools.email_oauth import account_from_oauth_token, oauth_provider
from job_agent.utils.config import settings
from job_agent.web import WebState


def _user() -> web.AuthUser:
    return {"id": 42, "email": "login@example.de", "created_at": "now"}


def test_web_oauth_start_and_callback_store_oauth_account(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "email_oauth_google_client_id", "client-id")
    monkeypatch.setattr(settings, "email_oauth_google_client_secret", "client-secret")
    monkeypatch.setattr(settings, "email_oauth_redirect_base", "http://127.0.0.1:7860")
    state = WebState()
    user = _user()

    start = web._start_email_oauth_from_payload(
        {"provider": "google", "email": "me@example.de"},
        state,
        user,
        host_header="127.0.0.1:7860",
    )
    query = parse_qs(urlparse(str(start["authorization_url"])).query)
    returned_state = query["state"][0]

    def fake_exchange(
        provider, *, code, redirect_uri, email_address, code_verifier
    ):  # type: ignore[no-untyped-def]
        assert provider.key == "google"
        assert code == "code-123"
        assert email_address == "me@example.de"
        assert len(code_verifier) >= 43
        return account_from_oauth_token(
            oauth_provider("google"),
            {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
            email_address=email_address,
        )

    monkeypatch.setattr(web, "exchange_code_for_account", fake_exchange)

    html = web._complete_email_oauth_from_params(
        {"code": ["code-123"], "state": [returned_state]},
        state,
        user,
    )
    account, source = web._load_email_account(user)

    assert "Verbunden" in html
    assert source == "local"
    assert account.auth_method == "oauth"
    assert account.access_token == "access"


def test_web_autopilot_schedule_start_stop(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = WebState()
    user = _user()

    started = web._configure_email_autopilot_schedule_from_payload(
        {
            "action": "start",
            "db_path": str(tmp_path / "data" / "schedule.db"),
            "interval_minutes": 5,
            "days": 7,
            "run_now": False,
        },
        state,
        user,
    )
    stopped = web._configure_email_autopilot_schedule_from_payload(
        {"action": "stop"},
        state,
        user,
    )

    assert started["enabled"] is True
    assert started["interval_minutes"] == 5
    assert stopped["enabled"] is False


def test_authenticated_user_never_inherits_environment_mailbox(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "email_smtp_host", "smtp.operator.example")
    monkeypatch.setattr(settings, "email_smtp_user", "operator@example.de")
    monkeypatch.setattr(settings, "email_smtp_password", "operator-secret")

    account, source = web._load_email_account(_user())

    assert source == "unconfigured"
    assert account.email_address == "login@example.de"
    assert account.smtp_host == ""
    assert account.smtp_password == ""
    assert account.dry_run is True


def test_oauth_redirect_rejects_external_plain_http(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "email_oauth_redirect_base", "http://jobs.example.org")

    with pytest.raises(ValueError, match="Basis-URL"):
        web._oauth_redirect_uri("attacker.invalid")
