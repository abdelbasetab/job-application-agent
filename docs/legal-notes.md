# Legal and Compliance Notes

This project is a student portfolio piece. Even so, a few things deserve a
paragraph here so we don't trip on them.

## 1. Job-board Terms of Service

We use the **Adzuna API** and the **Bundesagentur für Arbeit Jobsuche-API**
through their official documented endpoints (see ADR-0001). Both providers
require:

- A descriptive `User-Agent` header (set in `tools/job_search.py`).
- Respecting `429` rate-limit responses (httpx retries with backoff).
- Not redistributing the raw ad text outside the agent pipeline — we use it
  only to compute matches and to draft user-facing applications.

We deliberately **do not scrape** StepStone, LinkedIn, or Indeed — their ToS
forbid automated access. If a Sprint-3 fallback is added, it will only
target publicly-readable, robots.txt-allowed pages, with a clear user-opt-in.

## 2. GDPR / DSGVO

The application is **single-tenant** (one user, locally on their machine):

- The user's profile lives in `data/profile/profile.yaml` on disk.
- Job postings cached in SQLite contain only what the API already exposes
  publicly.
- No personal data leaves the machine except in:
  - LLM API calls (the profile + posting are sent to Anthropic).
  - Final application submission (which is the whole point).

If the project is ever multi-tenant (Sprint 5 dashboard), we'll need a
proper privacy notice and the Tracker's SQL schema will need an
`account_id` column. Out of scope for Sprint 1.

## 3. AI-Generated Content Disclosure

Generated cover letters are **drafts**. They are clearly labeled in their
Markdown footer as agent-produced, and the user must review them before
submission. We never auto-submit applications without explicit user action.

## 4. Open-Source Licensing

This project is MIT-licensed (see `pyproject.toml`). All dependencies are
permissively licensed (Apache-2.0, MIT, BSD).
