"""The four agents that make up the pipeline.

Scout discovers jobs, Matcher scores them against the user's profile,
Writer drafts a tailored application, and Tracker persists state.

Sprint 2 status:
- Scout: REAL + DEMO - live Adzuna/BA tools plus an offline demo scout.
- Matcher: MOCK - deterministic skill-overlap scoring (LLM arrives in Sprint 3).
- Writer: MOCK - templated cover letter (LLM arrives in Sprint 3).
- Tracker: REAL - writes to SQLite and supports the no-duplicate guard.
"""
