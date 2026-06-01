# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (uv recommended)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run the full pipeline
python -m job_agent.main run-pipeline
python -m job_agent.main run-pipeline --query "Werkstudent KI" --threshold 0.5 --limit 10

# Show persisted applications
python -m job_agent.main show-applications

# Run all tests
pytest

# Run a single test file
pytest tests/test_tracer_bullet.py

# Lint and type-check
ruff check src tests
mypy src
```

The installed CLI alias is `job-agent run-pipeline` (same as the `python -m` form).

## Architecture

A linear four-agent pipeline: **Scout → Matcher → Writer → Tracker**.

```
UserProfile + query ─▶ Scout ─▶ list[JobPosting]
                                       │
                                    Matcher ─▶ list[MatchResult]
                                                    │
                               filter score ≥ threshold
                                                    │
                      (per match) Writer ─▶ GeneratedApplication
                                                    │
                                               Tracker ─▶ ApplicationStatus (SQLite)
```

**The Pydantic schemas in `src/job_agent/schemas/` are the contracts between agents.** Each agent consumes and produces validated schema instances — no freeform string handoffs. `extra = "forbid"` enforces this at runtime.

### Key files

| File | Role |
| --- | --- |
| `src/job_agent/pipeline.py` | Orchestrates the four agents in sequence |
| `src/job_agent/main.py` | Typer CLI entrypoint; `_demo_profile()` is the Sprint-1 placeholder profile |
| `src/job_agent/schemas/` | Pydantic models: `JobPosting`, `UserProfile`, `MatchResult`, `GeneratedApplication`, `ApplicationStatus` |
| `src/job_agent/agents/scout.py` | **Current assignment** — stub returns 3 hardcoded fixtures; replace body of `run_scout()` with a CrewAI implementation |
| `src/job_agent/agents/matcher.py` | Sprint-1 deterministic skill-overlap scorer; LLM scoring arrives in Sprint 3 |
| `src/job_agent/agents/writer.py` | Sprint-1 mock writer; LLM drafting arrives in Sprint 3 |
| `src/job_agent/agents/tracker.py` | Persists `ApplicationStatus` to SQLite via `Store` |
| `src/job_agent/memory/store.py` | SQLite wrapper; three tables (`jobs`, `applications`, `status`) storing full Pydantic JSON dumps, keyed by `job_id` |
| `src/job_agent/tools/job_search.py` | Adzuna + BA-Jobsuche adapters (stubs in Sprint 1; real HTTP calls in Sprint 2) |
| `src/job_agent/prompts/scout.md` | System prompt template to drop into the CrewAI Scout Agent |
| `src/job_agent/utils/config.py` | Reads `.env`; exposes `settings` singleton with all API keys and paths |

### LLM & framework choices (from ADRs)

- **CrewAI** for agent orchestration (ADR-0002). Tools are `@tool`-decorated functions — `tools/job_search.py` is already shaped for this.
- **Anthropic Claude** as default LLM (ADR-0003). Use `claude-sonnet-4-6` for general work, `claude-haiku-4-5` for cheap/batch calls.
- Configure via `LLM_MODEL` in `.env`; code reads it through `settings.llm_model`.
- For CrewAI + Anthropic: `from crewai import LLM; llm = LLM(model="anthropic/claude-sonnet-4-6", temperature=0.2)`

### Environment variables (`.env`)

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...          # optional fallback
LLM_MODEL=claude-sonnet-4-6
LLM_TEMPERATURE=0.2
ADZUNA_APP_ID=...           # Sprint 2
ADZUNA_APP_KEY=...          # Sprint 2
SQLITE_PATH=./data/job_agent.db
CHROMA_PATH=./data/chroma_db
```

### Sprint status (as of Sprint 1)

The next coding task is implementing `agents/scout.py`. The function signature must stay identical:

```python
def run_scout(profile: UserProfile, query: str | None = None, limit: int = 5) -> list[JobPosting]:
```

CrewAI's crew output is a raw string — strip Markdown fences before `json.loads`, then validate each entry with `JobPosting.model_validate(...)`. See the template comment at the top of `agents/scout.py` and `docs/sprint_1_handoff.md` for pitfalls.
