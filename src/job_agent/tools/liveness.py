"""Job-posting liveness check — is the ad still open?

Light-touch by design: a single HTTP GET (httpx, already a dependency)
classifies most cases via status code, redirects, and "no longer available"
text. An optional Playwright deep check (only if installed *and* requested)
inspects the rendered page for an apply button / real content.

It never raises: a blocked, empty, or timed-out probe returns
``status="unknown"`` so the pipeline degrades gracefully instead of crashing.

This is a courtesy availability check for a posting you already have — one
request per call, a normal User-Agent, no pagination, no anti-bot evasion, no
captcha handling.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from job_agent.schemas import JobPosting, LivenessResult
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger
from job_agent.utils.network_security import safe_http_get, validate_public_url

log = get_logger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; JobAgentLiveness/1.0; +local personal use)"

# Phrases that strongly indicate a posting is gone (German + English).
_EXPIRED_PHRASES = [
    "stelle nicht mehr verfügbar",
    "stelle nicht mehr verfuegbar",
    "stellenanzeige ist nicht mehr",
    "anzeige ist nicht mehr verfügbar",
    "nicht mehr verfügbar",
    "nicht mehr online",
    "stelle ist besetzt",
    "position bereits besetzt",
    "bewerbungsfrist ist abgelaufen",
    "bewerbungsphase ist beendet",
    "stellenangebot wurde deaktiviert",
    "diese stelle wurde geschlossen",
    "job not found",
    "no longer available",
    "no longer accepting applications",
    "position has been filled",
    "this job is no longer",
    "posting has expired",
    "vacancy is closed",
]
_NOT_FOUND_PHRASES = [
    "seite nicht gefunden",
    "page not found",
    "404 not found",
    "error 404",
]

# (status_code, final_url, body_text). Injectable so tests stay offline.
FetchResult = tuple[int, str, str]
FetchFn = Callable[[str, float], FetchResult]


def _http_fetch(url: str, timeout: float) -> FetchResult:
    return safe_http_get(
        url,
        timeout=timeout,
        max_bytes=40_000,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
        allow_private=settings.allow_private_network_services,
    )


def check_job_liveness(
    job: JobPosting, *, deep: bool = False, fetch: FetchFn | None = None
) -> LivenessResult:
    """Convenience wrapper: check a :class:`JobPosting`'s URL."""
    return check_liveness(str(job.url), deep=deep, fetch=fetch)


def check_liveness(
    url: str,
    *,
    deep: bool = False,
    timeout: float = 10.0,
    fetch: FetchFn | None = None,
) -> LivenessResult:
    """Probe ``url`` and return a structured :class:`LivenessResult`."""
    probe = fetch or _http_fetch
    try:
        status_code, final_url, body = probe(url, timeout)
    except Exception as exc:
        log.warning("[liveness] HTTP probe failed for %s: %s", url, exc)
        return LivenessResult(
            url=url,
            status="unknown",
            confidence=0.3,
            reason=f"Abruf nicht möglich ({type(exc).__name__}) — Status unsicher.",
            checked_via="http",
        )

    result = _classify_http(url, status_code, final_url, body)
    if deep and result.status == "unknown":
        deeper = _playwright_probe(url, timeout)
        if deeper is not None:
            return deeper
    return result


def _classify_http(url: str, status_code: int, final_url: str, body: str) -> LivenessResult:
    if status_code in (404, 410):
        return LivenessResult(
            url=url,
            status="expired",
            confidence=0.9,
            reason=f"HTTP {status_code} — Seite nicht (mehr) vorhanden.",
            checked_via="http",
        )
    if status_code in (401, 403, 429):
        return LivenessResult(
            url=url,
            status="unknown",
            confidence=0.3,
            reason=f"HTTP {status_code} — Zugriff blockiert/limitiert, Status unsicher.",
            checked_via="http",
        )
    if status_code >= 500:
        return LivenessResult(
            url=url,
            status="unknown",
            confidence=0.3,
            reason=f"HTTP {status_code} — Serverfehler, Status unsicher.",
            checked_via="http",
        )
    if status_code >= 400:
        return LivenessResult(
            url=url,
            status="unknown",
            confidence=0.4,
            reason=f"HTTP {status_code} — unklarer Status.",
            checked_via="http",
        )

    lowered = body.lower()
    for phrase in _EXPIRED_PHRASES:
        if phrase in lowered:
            return LivenessResult(
                url=url,
                status="expired",
                confidence=0.85,
                reason=f"Hinweis im Seiteninhalt: „{phrase}“.",
                checked_via="http",
            )
    for phrase in _NOT_FOUND_PHRASES:
        if phrase in lowered:
            return LivenessResult(
                url=url,
                status="expired",
                confidence=0.7,
                reason=f"„Nicht gefunden“-Hinweis im Seiteninhalt: „{phrase}“.",
                checked_via="http",
            )
    if not body.strip():
        return LivenessResult(
            url=url,
            status="unknown",
            confidence=0.4,
            reason="Leere Antwort — Status unsicher.",
            checked_via="http",
        )
    return LivenessResult(
        url=url,
        status="live",
        confidence=0.7,
        reason=f"HTTP {status_code}, Inhalt vorhanden, keine Ablauf-Hinweise erkannt.",
        checked_via="http",
    )


def _playwright_probe(url: str, timeout: float) -> LivenessResult | None:
    """Render the page in a headless browser. Returns None if unavailable/failed."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        validate_public_url(url, allow_private=settings.allow_private_network_services)
        with sync_playwright() as runner:
            browser = runner.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=_USER_AGENT)

                def guard_navigation(route: Any, request: Any) -> None:
                    # Playwright may follow redirects independently of httpx.
                    # Validate each main-frame navigation before it reaches the network.
                    is_navigation = bool(request.is_navigation_request())
                    frame = request.frame
                    if is_navigation and frame == page.main_frame:
                        try:
                            validate_public_url(
                                str(request.url),
                                allow_private=settings.allow_private_network_services,
                            )
                        except ValueError:
                            route.abort()
                            return
                    route.continue_()

                page.route("**/*", guard_navigation)
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                content = (page.content() or "")[:200_000].lower()
            finally:
                browser.close()
    except Exception as exc:
        log.warning("[liveness] Playwright probe failed for %s: %s", url, exc)
        return None

    for phrase in _EXPIRED_PHRASES:
        if phrase in content:
            return LivenessResult(
                url=url,
                status="expired",
                confidence=0.9,
                reason=f"Browser-Check: „{phrase}“ im gerenderten Inhalt.",
                checked_via="playwright",
            )
    if any(token in content for token in ("jetzt bewerben", "bewerben", "apply now", "apply")):
        return LivenessResult(
            url=url,
            status="live",
            confidence=0.8,
            reason="Browser-Check: Bewerben-/Apply-Element im gerenderten Inhalt.",
            checked_via="playwright",
        )
    return LivenessResult(
        url=url,
        status="unknown",
        confidence=0.4,
        reason="Browser-Check: kein eindeutiges Signal.",
        checked_via="playwright",
    )
