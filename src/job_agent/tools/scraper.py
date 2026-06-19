"""Optional, polite job-detail scraper — ADR-0005.

Held in reserve per ADR-0001: APIs remain the primary source. This module only
enriches the *detail page of a posting already found via an API* (it never
discovers jobs by scraping a board's search results). It is **off by default**
(``ENABLE_SCRAPER``), respects ``robots.txt``, rate-limits requests, and sends
an identifying User-Agent.
"""

from __future__ import annotations

import html as _html
import re
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

_USER_AGENT = "JobApplicationAgent/1.0 (student project; polite, rate-limited)"
_HTTP_TIMEOUT = 15.0

_lock = threading.Lock()
_last_request = 0.0
_robots_cache: dict[str, RobotFileParser] = {}

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _robots_allows(url: str) -> bool:
    """Conservative robots.txt check: disallow if we cannot confirm permission."""
    try:
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
    except Exception:
        return False
    parser = _robots_cache.get(root)
    if parser is None:
        parser = RobotFileParser()
        parser.set_url(root + "/robots.txt")
        try:
            parser.read()
        except Exception:
            _robots_cache[root] = parser
            return False
        _robots_cache[root] = parser
    try:
        return parser.can_fetch(_USER_AGENT, url)
    except Exception:
        return False


def _rate_limit() -> None:
    global _last_request
    with _lock:
        wait = settings.scraper_min_interval - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def html_to_text(markup: str) -> str:
    """Strip a job-detail HTML page down to readable plain text."""
    cleaned = _SCRIPT_STYLE_RE.sub(" ", markup)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = _html.unescape(cleaned)
    return _WS_RE.sub(" ", cleaned).strip()


def scrape_job_text(url: str, max_chars: int = 6000) -> str:
    """Fetch and clean a single job-detail page. Returns "" unless enabled+allowed."""
    if not settings.enable_scraper:
        return ""
    if not url.startswith("http"):
        return ""
    if not _robots_allows(url):
        log.info("[scraper] robots.txt disallows or unknown — skipping %s", url)
        return ""
    _rate_limit()
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("[scraper] fetch failed for %s: %s", url, exc)
        return ""
    text = html_to_text(response.text)
    log.info("[scraper] extracted %d chars from %s", len(text), url)
    return text[:max_chars]
