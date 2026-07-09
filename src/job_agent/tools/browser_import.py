"""Assisted, human-in-the-loop browser import for login-gated job boards.

Flow: a real (visible) browser opens; **you** log in and run **your** search;
the tool then reads the results page you are looking at and imports those
postings. It is deliberately *not* a crawler:

* no automated login (you type your own credentials),
* no captcha solving, no anti-bot stealth,
* no pagination / bulk crawling — one human-driven page read per call,
* no automatic applying.

Login-gated boards (Indeed / StepStone / XING) are intentionally outside the
core search providers; this is the private, local import path for them.
Selectors are best-effort and may need tuning against the live page — the
parser is separated from the browser so it can be unit-tested on fixtures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

from job_agent.schemas import JobPosting
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

ImportSource = Literal["indeed", "stepstone", "xing"]


@dataclass(frozen=True)
class SiteConfig:
    key: ImportSource
    label: str
    start_url: str
    base_url: str
    # Candidate CSS selectors for a single result card (tried in order).
    card_selectors: list[str]
    title_selectors: list[str]
    company_selectors: list[str]
    location_selectors: list[str]
    link_selectors: list[str] = field(default_factory=list)


SITES: dict[ImportSource, SiteConfig] = {
    "indeed": SiteConfig(
        key="indeed",
        label="Indeed",
        start_url="https://de.indeed.com/",
        base_url="https://de.indeed.com",
        card_selectors=["div.job_seen_beacon", "[data-testid='slider_item']", "div.cardOutline"],
        title_selectors=["h2.jobTitle a", "a.jcs-JobTitle", "h2 a"],
        company_selectors=["[data-testid='company-name']", "span.companyName"],
        location_selectors=["[data-testid='text-location']", "div.companyLocation"],
        link_selectors=["h2.jobTitle a", "a.jcs-JobTitle", "h2 a"],
    ),
    "stepstone": SiteConfig(
        key="stepstone",
        label="StepStone",
        start_url="https://www.stepstone.de/",
        base_url="https://www.stepstone.de",
        card_selectors=["article[data-testid='job-item']", "[data-at='job-item']", "article"],
        title_selectors=["[data-at='job-item-title']", "a[data-at='job-item-title']", "h2 a"],
        company_selectors=["[data-at='job-item-company-name']", "span"],
        location_selectors=["[data-at='job-item-location']", "[data-at='job-item-work-from-home']"],
        link_selectors=["[data-at='job-item-title']", "a[href*='/stellenangebote']", "h2 a"],
    ),
    "xing": SiteConfig(
        key="xing",
        label="XING Jobs",
        start_url="https://www.xing.com/jobs/search",
        base_url="https://www.xing.com",
        card_selectors=["[data-testid='job-card']", "article", "li[class*='job']"],
        title_selectors=["[data-testid='job-title']", "h2", "h3"],
        company_selectors=["[data-testid='job-company']", "[data-testid='company-name']"],
        location_selectors=["[data-testid='job-location']", "[data-testid='location']"],
        link_selectors=["a[href*='/jobs/']", "a"],
    ),
}


def _clean(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _absolute_url(href: str, base_url: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    absolute = href if href.startswith("http") else urljoin(base_url + "/", href)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    # Drop tracking fragments but keep the query (often holds the job id).
    return absolute.split("#", 1)[0]


def _source_id_from_url(url: str) -> str:
    """A stable per-posting id from the URL (query id if present, else path hash)."""
    parsed = urlparse(url)
    for key in ("jk", "jobId", "id", "stellenangebot"):
        match = re.search(rf"(?:^|&){key}=([^&]+)", parsed.query)
        if match:
            return match.group(1)
    slug = (parsed.path.rstrip("/").rsplit("/", 1)[-1]) if parsed.path else ""
    if slug:
        return slug
    return sha256(url.encode("utf-8")).hexdigest()[:16]


def _stable_id(source: str, source_id: str) -> str:
    return sha256(f"{source}:{source_id}".encode()).hexdigest()[:20]


def cards_to_postings(cards: list[dict[str, str]], *, source: ImportSource) -> list[JobPosting]:
    """Pure mapping: raw result-card dicts -> validated, de-duplicated JobPostings."""
    cfg = SITES[source]
    out: list[JobPosting] = []
    seen: set[str] = set()
    for card in cards:
        url = _absolute_url(card.get("url", ""), cfg.base_url)
        title = _clean(card.get("title", ""))
        if not url or not title:
            continue
        source_id = _source_id_from_url(url)
        job_id = _stable_id(source, source_id)
        if job_id in seen:
            continue
        seen.add(job_id)
        try:
            out.append(
                JobPosting(
                    id=job_id,
                    source=source,
                    source_id=source_id,
                    url=url,  # type: ignore[arg-type]  # pydantic coerces str -> HttpUrl
                    title=title,
                    company=_clean(card.get("company", "")) or "Unbekannt",
                    location=_clean(card.get("location", "")),
                    description=_clean(card.get("snippet", "")),
                )
            )
        except Exception as exc:
            log.warning("[browser-import] dropping a card: %s", exc)
    return out


def _first_text(node: Any, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            found = node.query_selector(selector)
        except Exception:
            found = None
        if found is not None:
            try:
                text = str(found.inner_text() or "")
            except Exception:
                text = ""
            if text.strip():
                return text
    return ""


def _first_href(node: Any, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            found = node.query_selector(selector)
        except Exception:
            found = None
        if found is not None:
            try:
                href = found.get_attribute("href")
            except Exception:
                href = None
            if href:
                return str(href)
    return ""


def extract_cards(page: Any, cfg: SiteConfig) -> list[dict[str, str]]:
    """Read the currently displayed results page into raw card dicts (live DOM)."""
    elements: list[Any] = []
    for selector in cfg.card_selectors:
        try:
            elements = page.query_selector_all(selector)
        except Exception:
            elements = []
        if elements:
            log.info("[browser-import] %d cards via '%s'", len(elements), selector)
            break

    cards: list[dict[str, str]] = []
    for element in elements:
        cards.append(
            {
                "title": _first_text(element, cfg.title_selectors),
                "company": _first_text(element, cfg.company_selectors),
                "location": _first_text(element, cfg.location_selectors),
                "url": _first_href(element, cfg.link_selectors or cfg.title_selectors),
                "snippet": "",
            }
        )
    return cards


def run_assisted_import(
    site: ImportSource,
    *,
    limit: int = 25,
    wait_for_user: Any = None,
    headless: bool = False,
) -> list[JobPosting]:
    """Open a visible browser, let the user log in + search, import the visible page.

    ``wait_for_user(message)`` is called after the browser opens and must block
    until the user has logged in and run their search (the CLI passes an
    ``input()``-based prompt). Raises a clear error if Playwright is missing.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Browser-Import braucht Playwright. Installiere es mit:\n"
            "  pip install playwright && playwright install chromium"
        ) from exc

    if site not in SITES:
        raise ValueError(f"Unbekannte Seite '{site}'. Erlaubt: {', '.join(SITES)}.")
    cfg = SITES[site]
    prompt = wait_for_user or _default_prompt

    postings: list[JobPosting] = []
    with sync_playwright() as runner:
        browser = runner.chromium.launch(headless=headless)
        try:
            page = browser.new_context(locale="de-DE").new_page()
            page.goto(cfg.start_url, wait_until="domcontentloaded")
            prompt(
                f"\n[{cfg.label}] Bitte im geöffneten Browser einloggen und deine Suche "
                "ausführen.\nWenn die Ergebnisliste sichtbar ist, hier ENTER drücken …"
            )
            cards = extract_cards(page, cfg)
        finally:
            browser.close()

    postings = cards_to_postings(cards, source=site)[:limit]
    log.info("[browser-import] imported %d postings from %s", len(postings), cfg.label)
    return postings


def _default_prompt(message: str) -> None:
    input(message)
