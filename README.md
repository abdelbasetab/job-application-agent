# Job Application Agent

A multi-agent system for the German student job-search pipeline:
**find -> match -> draft -> track**.

Built as the portfolio project for the *AI Agents & RAG Systems* module
(Westfaelische Hochschule, Prof. Dr. Gleim).

## What It Does

| Agent | Current role |
| --- | --- |
| Scout | Finds job postings via Adzuna + BA-Jobsuche, with an offline demo scout for stable presentations |
| Matcher | Scores postings against the candidate profile with deterministic skill overlap |
| Writer | Drafts a German cover letter from a template |
| Tracker | Persists jobs, drafted applications, and status records in SQLite |

All handoffs use typed Pydantic schemas instead of freeform strings.

## Current Status

Sprint 2 is implemented as code, with one important demo distinction:

- Offline demo path is stable and does not need internet, API keys, or Ollama.
- Live Scout path is implemented, but depends on external API availability,
  Adzuna credentials, and the configured LLM.
- Matcher and Writer are still Sprint-1-style deterministic/template logic.
  LLM-backed matching and writing are planned for Sprint 3.

## Quick Start

```bash
# Install project dependencies
uv pip install -e ".[dev]"

# Run the stable offline Sprint-2 demo
python -m job_agent.main run-pipeline --demo --reset-demo-db --query "Werkstudent KI" --limit 5 --threshold 0.5

# Show generated draft applications
python -m job_agent.main show-applications --demo

# Run offline tests
pytest
```

The demo command writes to `./data/demo_job_agent.db` by default, so it does
not mix presentation data with the normal application database.

## Live Scout

The live Scout uses:

- Adzuna: requires `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`
- BA-Jobsuche: public endpoint, no API key expected
- CrewAI + configured LLM provider for tool orchestration

Configure `.env` from `.env.example`, then run:

```bash
python -m job_agent.main run-pipeline --query "Werkstudent KI" --limit 5 --threshold 0.5
pytest -m integration
```

If Adzuna credentials are missing or BA-Jobsuche rejects the request, use the
offline `--demo` mode for the Sprint review.

## Repo Layout

```text
src/job_agent/
  main.py              Typer CLI entrypoint
  pipeline.py          Orchestrates Scout -> Matcher -> Writer -> Tracker
  schemas/             Pydantic contracts between agents
  agents/              scout.py, demo_scout.py, matcher.py, writer.py, tracker.py
  tools/               job_search.py live API adapters
  memory/              store.py SQLite persistence
  prompts/             Prompt templates for later LLM-backed agents
  utils/               Config and logging

tests/                 Offline unit tests + integration tests
docs/                  ADRs, legal notes, Sprint 1 handoff
data/                  Local profile and SQLite data
```

## Test Status

Expected offline result:

```bash
pytest
# 12 passed, 3 deselected
```

Integration tests are intentionally separate:

```bash
pytest -m integration
```

They hit real services and may fail when credentials or API access are not
available.
