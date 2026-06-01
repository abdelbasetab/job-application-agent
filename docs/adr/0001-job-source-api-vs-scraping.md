# ADR-0001: Use Job APIs, not Scraping, for Scout's Data Source

- **Status:** Accepted
- **Date:** 2026-05-11
- **Sprint:** 1

## Context

The Scout agent needs a stream of fresh German tech-job postings. The two
realistic options are:

1. **Scraping** the public job-board frontends (StepStone, LinkedIn, Indeed)
   with Playwright or Selenium.
2. **Public job-search APIs** — primarily Adzuna (international) and the
   Bundesagentur für Arbeit Jobsuche-API (Germany-only, official).

## Decision

**Use APIs as the primary source.** Sprint 2 will integrate:

- **Adzuna** (https://developer.adzuna.com/) — free tier of 1 000 calls/month,
  covers Germany, returns JSON with title / company / location / description /
  redirect URL. App-ID + App-Key, no OAuth.
- **Bundesagentur für Arbeit Jobsuche-API** — no key needed, public REST,
  Germany-only, returns far more raw text per ad than Adzuna.

Scraping is held in reserve as a Sprint-3 *optional* fallback for postings
that appear only on StepStone or LinkedIn.

## Why

| Criterion | API | Scraping |
| --- | --- | --- |
| Legal / ToS risk | Low | High — LinkedIn ToS explicitly forbids it |
| GDPR exposure | Provider handles it | We handle it for every ad |
| Maintenance | Stable schemas | Selectors break weekly |
| Latency | ~200 ms | ~5-30 s per page |
| Rate limit | Documented | Bot-detection / IP bans |
| Demo reliability | High | A broken selector kills the live demo |

For a 5-sprint student project, the cost/benefit overwhelmingly favors APIs.

## Consequences

- Sprint 2's Scout uses only `adzuna_search` and `ba_jobsuche_search`.
- We accept that some niche postings (esp. small DACH startups on LinkedIn-only)
  are out of reach for now.
- Provider-specific normalization lives in `agents/scout.py`, *not* in
  `tools/job_search.py`. The tools layer returns raw dicts so we can mock
  them in tests easily.
