"""SMTP/IMAP connection checks for the web settings page.

The checks authenticate and verify the mailbox connection without sending an
email or reading message contents. Results are intentionally safe for the UI:
no passwords, tokens, or server responses containing secrets are returned.
"""

from __future__ import annotations

import base64
import imaplib
import smtplib
from typing import Any, Literal

from job_agent.tools.email_account import EmailAccount

ConnectionKind = Literal["smtp", "imap", "both"]


def test_email_connections(
    account: EmailAccount,
    *,
    kind: ConnectionKind = "both",
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Return SMTP/IMAP readiness checks for an account."""
    result: dict[str, Any] = {
        "ok": True,
        "account": {
            "email_address": account.email_address,
            "provider": account.provider,
            "auth_method": account.auth_method,
        },
    }
    if kind in {"smtp", "both"}:
        result["smtp"] = test_smtp_connection(account, timeout=timeout)
    if kind in {"imap", "both"}:
        result["imap"] = test_imap_connection(account, timeout=timeout)
    return result


def test_smtp_connection(account: EmailAccount, *, timeout: float = 15.0) -> dict[str, Any]:
    """Authenticate to SMTP without sending a message."""
    host = account.smtp_host.strip()
    user = (account.smtp_user or account.email_address).strip()
    if not host:
        return _missing("smtp", "SMTP host fehlt.")
    if not user:
        return _missing("smtp", "SMTP user fehlt.")
    if account.auth_method == "oauth" and not account.access_token:
        return _missing("smtp", "OAuth access token fehlt.")
    if account.auth_method != "oauth" and not account.smtp_password:
        return _missing("smtp", "SMTP Passwort/App-Passwort fehlt.")

    try:
        with smtplib.SMTP(host, account.smtp_port, timeout=timeout) as smtp:
            smtp.ehlo()
            if account.use_tls:
                smtp.starttls()
                smtp.ehlo()
            if account.auth_method == "oauth":
                _smtp_xoauth2(smtp, user, account.access_token)
            else:
                smtp.login(user, account.smtp_password)
            smtp.noop()
    except smtplib.SMTPAuthenticationError:
        return _failure(
            "smtp",
            host,
            account.smtp_port,
            user,
            _auth_failure_message(account, "SMTP"),
        )
    except (OSError, smtplib.SMTPException, TimeoutError) as exc:
        return _failure(
            "smtp",
            host,
            account.smtp_port,
            user,
            f"{type(exc).__name__}: Verbindung nicht erfolgreich.",
        )
    return _success(
        "smtp",
        host,
        account.smtp_port,
        user,
        "SMTP Login erfolgreich. Es wurde keine E-Mail gesendet.",
    )


def test_imap_connection(account: EmailAccount, *, timeout: float = 15.0) -> dict[str, Any]:
    """Authenticate to IMAP and select the configured folder read-only."""
    host = account.imap_host.strip()
    user = (account.imap_user or account.email_address).strip()
    folder = account.imap_folder.strip() or "INBOX"
    if not host:
        return _missing("imap", "IMAP host fehlt.")
    if not user:
        return _missing("imap", "IMAP user fehlt.")
    if account.auth_method == "oauth" and not account.access_token:
        return _missing("imap", "OAuth access token fehlt.")
    if account.auth_method != "oauth" and not account.imap_password:
        return _missing("imap", "IMAP Passwort/App-Passwort fehlt.")

    try:
        with imaplib.IMAP4_SSL(host, account.imap_port, timeout=timeout) as imap:
            if account.auth_method == "oauth":
                imap.authenticate("XOAUTH2", lambda _: _imap_xoauth2(user, account.access_token))
            else:
                imap.login(user, account.imap_password)
            status, _data = imap.select(folder, readonly=True)
            if status != "OK":
                return _failure(
                    "imap",
                    host,
                    account.imap_port,
                    user,
                    f"Ordner '{folder}' konnte nicht geoeffnet werden.",
                )
    except imaplib.IMAP4.error:
        return _failure(
            "imap",
            host,
            account.imap_port,
            user,
            _auth_failure_message(account, "IMAP"),
        )
    except (OSError, TimeoutError) as exc:
        return _failure(
            "imap",
            host,
            account.imap_port,
            user,
            f"{type(exc).__name__}: Verbindung nicht erfolgreich.",
        )
    return _success(
        "imap",
        host,
        account.imap_port,
        user,
        f"IMAP Login erfolgreich. Ordner '{folder}' ist erreichbar.",
    )


def _success(protocol: str, host: str, port: int, user: str, message: str) -> dict[str, Any]:
    return {
        "ok": True,
        "configured": True,
        "protocol": protocol,
        "host": host,
        "port": port,
        "user": user,
        "message": message,
    }


def _failure(protocol: str, host: str, port: int, user: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "configured": True,
        "protocol": protocol,
        "host": host,
        "port": port,
        "user": user,
        "message": message,
    }


def _missing(protocol: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "configured": False,
        "protocol": protocol,
        "host": "",
        "port": 0,
        "user": "",
        "message": message,
    }


def _auth_failure_message(account: EmailAccount, protocol: str) -> str:
    marker = f"{account.smtp_host} {account.imap_host} {account.smtp_user} {account.imap_user} {account.email_address}".lower()
    if "gmail.com" in marker or "googlemail.com" in marker:
        return (
            f"{protocol}: Gmail lehnt die Anmeldung ab. Nutze kein normales Google-Passwort, "
            "sondern ein 16-stelliges App-Passwort mit aktivierter 2-Faktor-Anmeldung "
            "oder OAuth. App-Passwort ohne Leerzeichen speichern."
        )
    return f"{protocol}: Authentifizierung fehlgeschlagen. App-Passwort/OAuth pruefen."


def _smtp_xoauth2(smtp: smtplib.SMTP, user: str, access_token: str) -> None:
    auth = base64.b64encode(
        f"user={user}\x01auth=Bearer {access_token}\x01\x01".encode()
    ).decode("ascii")
    code, response = smtp.docmd("AUTH", "XOAUTH2 " + auth)
    if code >= 400:
        raise smtplib.SMTPAuthenticationError(code, response)


def _imap_xoauth2(user: str, access_token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {access_token}\x01\x01".encode()
