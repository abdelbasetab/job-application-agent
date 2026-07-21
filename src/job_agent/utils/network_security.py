"""Network egress validation for user-controlled URLs and service hosts."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

_REDIRECT_CODES = {301, 302, 303, 307, 308}


def validate_public_host(host: str, port: int, *, allow_private: bool = False) -> str:
    """Resolve ``host`` and reject local/private/special-use destinations."""
    normalized = host.strip().rstrip(".").casefold()
    if not normalized or len(normalized) > 253:
        raise ValueError("Ungueltiger Netzwerk-Host.")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        if allow_private:
            return normalized
        raise ValueError("Lokale Netzwerkziele sind nicht erlaubt.")
    try:
        literal = ipaddress.ip_address(normalized.strip("[]"))
        addresses = {literal}
    except ValueError:
        try:
            rows = socket.getaddrinfo(normalized, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("Netzwerk-Host konnte nicht aufgeloest werden.") from exc
        addresses = {ipaddress.ip_address(row[4][0]) for row in rows}
    if not addresses:
        raise ValueError("Netzwerk-Host hat keine Adresse.")
    if not allow_private and any(not address.is_global for address in addresses):
        raise ValueError("Private, lokale oder reservierte Netzwerkziele sind nicht erlaubt.")
    return normalized


def validate_public_url(url: str, *, allow_private: bool = False) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Nur vollstaendige HTTP(S)-URLs sind erlaubt.")
    if parsed.username or parsed.password:
        raise ValueError("URLs mit eingebetteten Zugangsdaten sind nicht erlaubt.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("Ungueltiger URL-Port.") from exc
    validate_public_host(parsed.hostname, port, allow_private=allow_private)
    return url.strip()


def safe_http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    max_bytes: int = 40_000,
    max_redirects: int = 5,
    allow_private: bool = False,
) -> tuple[int, str, str]:
    """GET with destination validation before the request and every redirect."""
    current = validate_public_url(url, allow_private=allow_private)
    with httpx.Client(follow_redirects=False, timeout=timeout, headers=headers) as client:
        for _ in range(max_redirects + 1):
            with client.stream("GET", current) as response:
                if response.status_code in _REDIRECT_CODES and response.headers.get("location"):
                    current = validate_public_url(
                        urljoin(current, response.headers["location"]),
                        allow_private=allow_private,
                    )
                    continue
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    remaining = max_bytes - size
                    if remaining <= 0:
                        break
                    chunks.append(chunk[:remaining])
                    size += min(len(chunk), remaining)
                raw = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                try:
                    body = raw.decode(encoding, errors="replace")
                except LookupError:
                    body = raw.decode("utf-8", errors="replace")
                return response.status_code, str(response.url), body
    raise ValueError("Zu viele HTTP-Weiterleitungen.")
