"""Assisted browser import: the pure card->JobPosting mapping (offline)."""

from __future__ import annotations

import pytest

from job_agent.tools.browser_import import (
    _absolute_url,
    _source_id_from_url,
    _stable_id,
    cards_to_postings,
)


def test_cards_to_postings_maps_and_dedups() -> None:
    cards = [
        {
            "title": "Werkstudent KI",
            "company": "ACME GmbH",
            "location": "Essen",
            "url": "https://de.indeed.com/viewjob?jk=abc123",
        },
        {  # exact duplicate -> dropped
            "title": "Werkstudent KI",
            "company": "ACME GmbH",
            "location": "Essen",
            "url": "https://de.indeed.com/viewjob?jk=abc123",
        },
        {  # relative URL + missing company -> resolved + defaulted
            "title": "Data Engineer",
            "company": "",
            "location": "",
            "url": "/rc/clk?jk=xyz789",
        },
    ]
    postings = cards_to_postings(cards, source="indeed")
    assert len(postings) == 2
    assert postings[0].source == "indeed"
    assert postings[0].source_id == "abc123"
    assert str(postings[0].url).startswith("https://de.indeed.com")
    assert postings[1].company == "Unbekannt"
    assert str(postings[1].url).startswith("https://de.indeed.com")


def test_cards_skip_invalid_url_or_missing_title() -> None:
    cards = [
        {"title": "", "company": "X", "location": "Y", "url": "https://x.de/job/1"},
        {"title": "Has title", "company": "X", "location": "Y", "url": "javascript:void(0)"},
        {
            "title": "Good",
            "company": "X",
            "location": "Y",
            "url": "https://www.stepstone.de/stellenangebote/123",
        },
    ]
    postings = cards_to_postings(cards, source="stepstone")
    assert len(postings) == 1
    assert postings[0].title == "Good"
    assert postings[0].source == "stepstone"


def test_source_id_prefers_query_id_then_slug() -> None:
    assert _source_id_from_url("https://de.indeed.com/viewjob?jk=ID123&x=1") == "ID123"
    assert _source_id_from_url("https://www.xing.com/jobs/essen-werkstudent-99") == "essen-werkstudent-99"


def test_absolute_url_rejects_non_http() -> None:
    assert _absolute_url("javascript:void(0)", "https://x.de") == ""
    assert _absolute_url("/job/1", "https://x.de") == "https://x.de/job/1"


def test_stable_id_deterministic_and_source_scoped() -> None:
    assert _stable_id("indeed", "abc") == _stable_id("indeed", "abc")
    assert len(_stable_id("indeed", "abc")) == 20
    assert _stable_id("indeed", "abc") != _stable_id("xing", "abc")


def test_unknown_source_raises() -> None:
    with pytest.raises(KeyError):
        cards_to_postings([], source="monster")  # type: ignore[arg-type]


@pytest.mark.integration
def test_extract_cards_against_fixture_page() -> None:
    """Exercise the real Playwright extraction against a local Indeed-like page.

    Marked integration (needs chromium; deselected by default). It proves the
    selector plumbing works — real sites may still need selector tuning.
    """
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from job_agent.tools.browser_import import SITES, extract_cards

    html = """<html><body>
      <div class="job_seen_beacon">
        <h2 class="jobTitle"><a href="/viewjob?jk=test123">Werkstudent KI</a></h2>
        <span data-testid="company-name">ACME GmbH</span>
        <div data-testid="text-location">Essen</div>
      </div>
      <div class="job_seen_beacon">
        <h2 class="jobTitle"><a href="/viewjob?jk=test456">Data Engineer</a></h2>
        <span data-testid="company-name">Beta AG</span>
        <div data-testid="text-location">Dortmund</div>
      </div>
    </body></html>"""
    with sync_playwright() as runner:
        browser = runner.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        cards = extract_cards(page, SITES["indeed"])
        browser.close()

    postings = cards_to_postings(cards, source="indeed")
    assert len(postings) == 2
    assert postings[0].source_id == "test123"
    assert postings[0].company == "ACME GmbH"
