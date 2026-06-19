"""Offline tests for the optional detail-page scraper (ADR-0005)."""

from __future__ import annotations

from job_agent.tools import scraper


def test_html_to_text_strips_tags_and_scripts():
    html = (
        "<html><head><style>.x{color:red}</style></head>"
        "<body><h1>Titel</h1><p>Python &amp; SQL</p>"
        "<script>evil()</script></body></html>"
    )
    text = scraper.html_to_text(html)
    assert "Titel" in text
    assert "Python & SQL" in text
    assert "evil()" not in text
    assert "<" not in text


def test_scrape_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(scraper.settings, "enable_scraper", False)
    assert scraper.scrape_job_text("https://example.com/jobs/1") == ""


def test_scrape_rejects_non_http(monkeypatch):
    monkeypatch.setattr(scraper.settings, "enable_scraper", True)
    assert scraper.scrape_job_text("ftp://x/y") == ""
