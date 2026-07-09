"""OAuth helpers for email integrations.

The module implements the local app flow used by the web UI. Network calls are
kept behind small functions so tests can stub them without touching real
Google/Microsoft services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# `datetime.UTC` is 3.11+ — the timezone.utc spelling keeps the module
# importable on older interpreters (see memory/auth_store.py).
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from job_agent.tools.email_account import EmailAccount
from job_agent.utils.config import settings

UTC = timezone.utc  # noqa: UP017


class HttpPost(Protocol):
    def __call__(
        self,
        url: str,
        *,
        data: dict[str, str],
        timeout: float,
    ) -> httpx.Response: ...


@dataclass(frozen=True)
class OAuthProvider:
    key: str
    label: str
    auth_url: str
    token_url: str
    scope: str
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    client_id: str
    client_secret: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def oauth_provider(provider: str) -> OAuthProvider:
    key = provider.strip().lower()
    if key in {"gmail", "google"}:
        return OAuthProvider(
            key="google",
            label="Gmail / Google",
            auth_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scope="https://mail.google.com/",
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            imap_host="imap.gmail.com",
            imap_port=993,
            client_id=settings.email_oauth_google_client_id or "",
            client_secret=settings.email_oauth_google_client_secret or "",
        )
    if key in {"outlook", "office365", "microsoft"}:
        return OAuthProvider(
            key="microsoft",
            label="Outlook / Microsoft 365",
            auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            scope=(
                "offline_access "
                "https://outlook.office.com/IMAP.AccessAsUser.All "
                "https://outlook.office.com/SMTP.Send"
            ),
            smtp_host="smtp.office365.com",
            smtp_port=587,
            imap_host="outlook.office365.com",
            imap_port=993,
            client_id=settings.email_oauth_microsoft_client_id or "",
            client_secret=settings.email_oauth_microsoft_client_secret or "",
        )
    raise ValueError("Unsupported email OAuth provider. Use 'google' or 'microsoft'.")


def oauth_provider_status() -> list[dict[str, Any]]:
    return [
        _provider_status(oauth_provider("google")),
        _provider_status(oauth_provider("microsoft")),
    ]


def build_authorization_url(
    provider: OAuthProvider,
    *,
    redirect_uri: str,
    state: str,
    login_hint: str = "",
) -> str:
    if not provider.configured:
        raise ValueError(f"{provider.label} OAuth ist nicht konfiguriert.")
    params = {
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{provider.auth_url}?{urlencode(params)}"


def exchange_code_for_account(
    provider: OAuthProvider,
    *,
    code: str,
    redirect_uri: str,
    email_address: str,
    http_post: HttpPost = httpx.post,
) -> EmailAccount:
    token = _token_request(
        provider,
        {
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        http_post=http_post,
    )
    return account_from_oauth_token(provider, token, email_address=email_address)


def refresh_oauth_account(
    account: EmailAccount,
    *,
    http_post: HttpPost = httpx.post,
) -> EmailAccount:
    if account.auth_method != "oauth":
        return account
    if not account.refresh_token:
        raise ValueError("OAuth refresh token is missing. Please reconnect the account.")
    provider = oauth_provider(account.provider)
    token = _token_request(
        provider,
        {
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
            "refresh_token": account.refresh_token,
            "grant_type": "refresh_token",
        },
        http_post=http_post,
    )
    merged = {
        **account.secret_dict(),
        "access_token": str(token.get("access_token") or ""),
        "refresh_token": str(token.get("refresh_token") or account.refresh_token),
        "token_scope": str(token.get("scope") or account.token_scope),
        "token_expires_at": _expires_at(token),
    }
    return EmailAccount(**_email_account_kwargs(merged))


def account_from_oauth_token(
    provider: OAuthProvider,
    token: dict[str, Any],
    *,
    email_address: str,
) -> EmailAccount:
    email = email_address.strip().lower()
    payload = {
        "email_address": email,
        "email_from": email,
        "smtp_host": provider.smtp_host,
        "smtp_port": provider.smtp_port,
        "smtp_user": email,
        "imap_host": provider.imap_host,
        "imap_port": provider.imap_port,
        "imap_user": email,
        "imap_folder": "INBOX",
        "provider": provider.key,
        "auth_method": "oauth",
        "access_token": str(token.get("access_token") or ""),
        "refresh_token": str(token.get("refresh_token") or ""),
        "token_scope": str(token.get("scope") or provider.scope),
        "token_expires_at": _expires_at(token),
        "use_tls": True,
    }
    return EmailAccount(**_email_account_kwargs(payload))


def _token_request(
    provider: OAuthProvider,
    data: dict[str, str],
    *,
    http_post: HttpPost,
) -> dict[str, Any]:
    if not provider.configured:
        raise ValueError(f"{provider.label} OAuth ist nicht konfiguriert.")
    response = http_post(provider.token_url, data=data, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise ValueError("OAuth provider did not return an access token.")
    return payload


def _expires_at(token: dict[str, Any]) -> str:
    raw: object = token.get("expires_in")
    if isinstance(raw, int):
        seconds = raw
    elif isinstance(raw, float):
        seconds = int(raw)
    elif isinstance(raw, str):
        try:
            seconds = int(raw)
        except ValueError:
            seconds = 3600
    else:
        seconds = 3600
    return (datetime.now(UTC) + timedelta(seconds=max(60, seconds))).isoformat()


def _provider_status(provider: OAuthProvider) -> dict[str, Any]:
    return {
        "key": provider.key,
        "label": provider.label,
        "configured": provider.configured,
        "scope": provider.scope,
    }


def _email_account_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = set(EmailAccount.__dataclass_fields__)
    return {key: value for key, value in payload.items() if key in allowed}
