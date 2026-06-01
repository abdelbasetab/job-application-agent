"""The four agents that make up the pipeline.

Scout discovers jobs, Matcher scores them against the user's profile,
Writer drafts a tailored application, and Tracker persists state.

Sprint 1 status:
- Scout:   STUB — you implement this with CrewAI after the tutorial.
- Matcher: MOCK — deterministic skill-overlap scoring (no LLM yet).
- Writer:  MOCK — templated cover letter (no LLM yet).
- Tracker: REAL — writes to SQLite (this one stays as-is).
"""
