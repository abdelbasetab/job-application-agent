"""Email account resolution for SMTP/IMAP and UI readiness.

Environment variables remain the default configuration path. The web UI can
optionally pass a per-user account loaded from the local credential store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from job_agent.schemas import UserProfile
from job_agent.utils.config import settings

AuthMethod = Literal["password", "oauth"]
_EMAIL_RE = re.compile(
    r"[a-z0-9][a-z0-9._%+\-]{0,63}@[a-z0-9][a-z0-9.\-]{0,253}\.[a-z]{2,24}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EmailAccount:
    email_address: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    use_tls: bool = True
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    provider: str = "custom"
    auth_method: AuthMethod = "password"
    access_token: str = ""
    refresh_token: str = ""
    token_expires_at: str = ""
    token_scope: str = ""

    @property
    def sender(self) -> str:
        return (self.email_from or self.email_address or self.smtp_user).strip()

    @property
    def oauth_ready(self) -> bool:
        return bool(self.access_token or self.refresh_token)

    @property
    def smtp_ready(self) -> bool:
        if not self.smtp_host:
            return False
        if self.auth_method == "oauth":
            return bool((self.smtp_user or self.email_address) and self.oauth_ready)
        return bool((self.smtp_user or self.email_address) and self.smtp_password)

    @property
    def imap_ready(self) -> bool:
        if not self.imap_host:
            return False
        if self.auth_method == "oauth":
            return bool((self.imap_user or self.email_address) and self.oauth_ready)
        return bool((self.imap_user or self.email_address) and self.imap_password)

    @property
    def oauth_expired(self) -> bool:
        if self.auth_method != "oauth" or not self.token_expires_at:
            return False
        try:
            expires_at = datetime.fromisoformat(self.token_expires_at)
        except ValueError:
            return True
        return expires_at <= datetime.now(expires_at.tzinfo) + timedelta(minutes=2)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "email_address": self.email_address,
            "email_from": self.email_from,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_user": self.smtp_user,
            "smtp_ready": self.smtp_ready,
            "imap_host": self.imap_host,
            "imap_port": self.imap_port,
            "imap_user": self.imap_user,
            "imap_folder": self.imap_folder,
            "imap_ready": self.imap_ready,
            "provider": self.provider,
            "auth_method": self.auth_method,
            "has_smtp_password": bool(self.smtp_password),
            "has_imap_password": bool(self.imap_password),
            "oauth_ready": self.oauth_ready,
            "has_refresh_token": bool(self.refresh_token),
            "token_expires_at": self.token_expires_at,
            "token_scope": self.token_scope,
            "use_tls": self.use_tls,
        }

    def secret_dict(self) -> dict[str, Any]:
        return {
            **self.safe_dict(),
            "smtp_password": self.smtp_password,
            "imap_password": self.imap_password,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
        }


def account_from_settings() -> EmailAccount:
    email_from = _clean_email(settings.email_from or "")
    smtp_user = _clean_email(settings.email_smtp_user or "", preferred=email_from)
    imap_user = _clean_email(settings.email_imap_user or "", preferred=smtp_user or email_from)
    smtp_host = settings.email_smtp_host or ""
    imap_host = settings.email_imap_host or ""
    return EmailAccount(
        email_address=email_from or smtp_user,
        smtp_host=smtp_host,
        smtp_port=settings.email_smtp_port,
        smtp_user=smtp_user,
        smtp_password=_clean_secret(settings.email_smtp_password or "", host=smtp_host, user=smtp_user),
        email_from=email_from,
        use_tls=settings.email_use_tls,
        imap_host=imap_host,
        imap_port=settings.email_imap_port,
        imap_user=imap_user,
        imap_password=_clean_secret(settings.email_imap_password or "", host=imap_host, user=imap_user),
        imap_folder=settings.email_imap_folder,
        provider="env",
        auth_method="password",
    )


def account_from_mapping(data: dict[str, Any], fallback_email: str = "") -> EmailAccount:
    fallback = _clean_email(fallback_email)
    email_address = _clean_email(str(data.get("email_address") or ""), preferred=fallback) or fallback
    smtp_user = _clean_email(str(data.get("smtp_user") or ""), preferred=email_address) or email_address
    imap_user = _clean_email(str(data.get("imap_user") or ""), preferred=smtp_user or email_address) or smtp_user
    smtp_host = str(data.get("smtp_host") or "").strip()
    imap_host = str(data.get("imap_host") or "").strip()
    email_from = (
        _clean_email(str(data.get("email_from") or ""), preferred=email_address)
        or email_address
        or smtp_user
    )
    auth_method: AuthMethod = (
        "oauth" if str(data.get("auth_method") or "password") == "oauth" else "password"
    )
    return EmailAccount(
        email_address=email_address,
        smtp_host=smtp_host,
        smtp_port=_int(data.get("smtp_port"), 587, 1, 65535),
        smtp_user=smtp_user,
        smtp_password=_clean_secret(str(data.get("smtp_password") or ""), host=smtp_host, user=smtp_user),
        email_from=email_from,
        use_tls=bool(data.get("use_tls", True)),
        imap_host=imap_host,
        imap_port=_int(data.get("imap_port"), 993, 1, 65535),
        imap_user=imap_user,
        imap_password=_clean_secret(str(data.get("imap_password") or ""), host=imap_host, user=imap_user),
        imap_folder=str(data.get("imap_folder") or "INBOX").strip() or "INBOX",
        provider=str(data.get("provider") or "custom").strip() or "custom",
        auth_method=auth_method,
        access_token=str(data.get("access_token") or ""),
        refresh_token=str(data.get("refresh_token") or ""),
        token_expires_at=str(data.get("token_expires_at") or ""),
        token_scope=str(data.get("token_scope") or ""),
    )


def email_identity_payload(
    profile: UserProfile | None,
    user_email: str | None = None,
    account: EmailAccount | None = None,
    account_source: str = "env",
) -> dict[str, Any]:
    resolved = account or account_from_settings()
    login_email = _clean_email(user_email or "")
    profile_email = _clean_email(profile.email if profile else "", preferred=login_email)
    sender = _clean_email(resolved.sender, preferred=login_email or profile_email)
    imap_user = _clean_email(resolved.imap_user, preferred=sender or login_email or profile_email)
    smtp_user = _clean_email(resolved.smtp_user, preferred=sender or login_email or profile_email)
    candidate = (
        sender
        if account_source == "local" and sender
        else login_email or sender or profile_email
    )
    warnings: list[str] = []
    if profile_email and sender and profile_email != sender:
        warnings.append("Profil-E-Mail und Absender unterscheiden sich.")
    if profile_email and imap_user and profile_email != imap_user:
        warnings.append("Profil-E-Mail und IMAP-Konto unterscheiden sich.")
    if resolved.auth_method == "oauth" and not resolved.oauth_ready:
        warnings.append("OAuth-Konto ist angelegt, aber es fehlt ein Zugriffstoken.")
    if resolved.auth_method == "oauth" and resolved.oauth_expired and resolved.refresh_token:
        warnings.append("OAuth-Zugriffstoken ist abgelaufen und wird beim naechsten Sync erneuert.")
    if resolved.auth_method == "oauth" and resolved.oauth_expired and not resolved.refresh_token:
        warnings.append("OAuth-Zugriffstoken ist abgelaufen. Bitte Konto neu verbinden.")
    if not resolved.smtp_ready and not settings.email_dry_run:
        warnings.append("Echter Versand ist aktiv, aber SMTP ist nicht vollstaendig.")
    if not resolved.imap_ready and not settings.email_sync_dry_run:
        warnings.append("Echter Inbox-Sync ist aktiv, aber IMAP ist nicht vollstaendig.")
    return {
        "profile_email": profile_email,
        "login_email": login_email,
        "candidate_email": candidate,
        "sender": sender,
        "smtp_user": smtp_user,
        "imap_user": imap_user,
        "smtp_ready": resolved.smtp_ready,
        "imap_ready": resolved.imap_ready,
        "email_dry_run": settings.email_dry_run,
        "email_sync_dry_run": settings.email_sync_dry_run,
        "auto_follow_up_send": settings.email_auto_follow_up_send,
        "account_source": account_source,
        "account": account_from_mapping(resolved.secret_dict(), fallback_email=candidate).safe_dict(),
        "warnings": warnings,
    }


def _clean_email(value: str, *, preferred: str = "") -> str:
    text = _normalize_email_text(value)
    if not text:
        return ""
    preferred_clean = _clean_email_exact(preferred)
    if preferred_clean and preferred_clean in text:
        return preferred_clean
    exact = _clean_email_exact(text)
    if exact:
        return exact
    for match in _EMAIL_RE.finditer(text):
        candidate = _clean_email_exact(match.group(0))
        if candidate:
            return candidate
    return ""


def _clean_email_exact(value: str) -> str:
    text = _normalize_email_text(value)
    if not text or not _EMAIL_RE.fullmatch(text):
        return ""
    local, domain = text.rsplit("@", 1)
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return ""
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return ""
    labels = domain.split(".")
    if any(not label or label.startswith("-") or label.endswith("-") for label in labels):
        return ""
    return text


def _normalize_email_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.removeprefix("mailto:")
    return text.strip(" \t\r\n<>.,;:()[]{}\"'")


def _clean_secret(value: str, *, host: str = "", user: str = "") -> str:
    secret = str(value or "").strip()
    marker = f"{host} {user}".lower()
    if "gmail.com" in marker or "googlemail.com" in marker:
        return "".join(secret.split())
    return secret


def _int(value: object, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            parsed = default
    else:
        parsed = default
    return max(minimum, min(maximum, parsed))
