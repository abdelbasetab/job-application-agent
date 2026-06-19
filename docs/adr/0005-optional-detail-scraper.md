# ADR-0005: Optional, Polite Job-Detail Scraper as an Enrichment Fallback

- **Status:** Accepted
- **Date:** 2026-06-18
- **Sprint:** 3
- **Extends:** [ADR-0001](0001-job-source-api-vs-scraping.md)

## Context

ADR-0001 chose **APIs over scraping** and explicitly kept scraping "in reserve
as a Sprint-3 optional fallback." Two Sprint-3 needs revived the topic:

1. The BA-Jobsuche *list* endpoint returns no description. (Solved primarily by
   the official BA *detail* API — `tools/job_search.py::ba_jobsuche_detail` —
   which is **not** scraping.)
2. Some postings (Adzuna redirects, niche boards) still expose their full text
   only on an HTML detail page.

## Decision

Add an **opt-in** `tools/scraper.py` that fetches the **detail page of a posting
already discovered via an API** and reduces it to plain text. It is used only as
the *last* enrichment step, after the BA detail API, and only when a posting
still has no description.

It is **off by default** (`ENABLE_SCRAPER=false`). When enabled it:

- never discovers jobs by scraping a board's search results — APIs stay primary;
- respects `robots.txt` (and is conservative: if robots can't be read, it skips);
- rate-limits requests (`SCRAPER_MIN_INTERVAL`, default 2 s);
- sends an identifying, honest User-Agent.

## Why

- Keeps ADR-0001's cost/benefit intact: the demo and tests never depend on a
  scraper (it is off by default; a broken selector cannot kill the demo).
- Enrichment ≠ discovery. Fetching one detail page for a job the user already
  found is far more defensible (ToS/GDPR) than mass-scraping search pages.
- Most enrichment is already handled by the **official** BA detail API; the
  scraper is a narrow fallback.

## Consequences

- New env flags: `ENABLE_SCRAPER`, `SCRAPER_MIN_INTERVAL`.
- `_enrich_descriptions` calls the scraper only when `settings.enable_scraper`
  is true and a posting still lacks a description after the BA detail step.
- We still accept that LinkedIn/StepStone-only discovery is out of scope.
