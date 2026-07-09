from __future__ import annotations

from job_agent.tools.email_oauth import (
    build_authorization_url,
    exchange_code_for_account,
    oauth_provider,
    refresh_oauth_account,
)
from job_agent.utils.config import settings


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


def test_build_google_oauth_authorization_url(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "email_oauth_google_client_id", "client-id")
    monkeypatch.setattr(settings, "email_oauth_google_client_secret", "client-secret")
    provider = oauth_provider("google")

    url = build_authorization_url(
        provider,
        redirect_uri="http://127.0.0.1:7860/api/oauth/email/callback",
        state="state-123",
        login_hint="me@example.de",
    )

    assert "client_id=client-id" in url
    assert "state=state-123" in url
    assert "login_hint=me%40example.de" in url
    assert "https%3A%2F%2Fmail.google.com%2F" in url


def test_exchange_code_creates_oauth_email_account(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "email_oauth_google_client_id", "client-id")
    monkeypatch.setattr(settings, "email_oauth_google_client_secret", "client-secret")
    calls: list[dict[str, str]] = []

    def fake_post(url: str, *, data: dict[str, str], timeout: float) -> FakeResponse:
        calls.append(data)
        return FakeResponse(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": "https://mail.google.com/",
            }
        )

    account = exchange_code_for_account(
        oauth_provider("google"),
        code="code-123",
        redirect_uri="http://localhost/callback",
        email_address="me@example.de",
        http_post=fake_post,
    )

    assert calls[0]["grant_type"] == "authorization_code"
    assert account.auth_method == "oauth"
    assert account.smtp_host == "smtp.gmail.com"
    assert account.imap_host == "imap.gmail.com"
    assert account.access_token == "access"
    assert account.refresh_token == "refresh"


def test_refresh_oauth_account_preserves_existing_refresh_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "email_oauth_google_client_id", "client-id")
    monkeypatch.setattr(settings, "email_oauth_google_client_secret", "client-secret")
    account = exchange_code_for_account(
        oauth_provider("google"),
        code="code-123",
        redirect_uri="http://localhost/callback",
        email_address="me@example.de",
        http_post=lambda *_args, **_kwargs: FakeResponse(
            {"access_token": "old", "refresh_token": "refresh", "expires_in": 60}
        ),
    )

    refreshed = refresh_oauth_account(
        account,
        http_post=lambda *_args, **_kwargs: FakeResponse(
            {"access_token": "new", "expires_in": 3600}
        ),
    )

    assert refreshed.access_token == "new"
    assert refreshed.refresh_token == "refresh"
