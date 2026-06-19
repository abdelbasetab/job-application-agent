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

# Read a CV (Lebenslauf) → structured profile via the LLM (KI-Connect/OpenAI)
python -m job_agent.main read-cv --cv data/profile/sample_cv.md
python -m job_agent.main run-pipeline --cv path/to/cv.pdf --llm-agents --query "Werkstudent KI"

# Offline-safe: demo jobs matched against a real CV (LLM only for the profile)
python -m job_agent.main run-pipeline --demo --reset-demo-db --cv data/profile/sample_cv.md

# Show persisted applications
python -m job_agent.main show-applications --demo

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

A linear pipeline. Sprint 3 adds a **Profiler** front-end that builds the
`UserProfile` from a real CV (`--cv`) via the LLM; otherwise a baked-in demo
profile (or a `--profile` YAML) is used.

```
CV file ─▶ Profiler (LLM) ─▶ UserProfile  (or demo_profile / --profile YAML)
                                  │
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
| `src/job_agent/pipeline.py` | Orchestrates Scout → Matcher → Writer → Tracker in sequence |
| `src/job_agent/main.py` | Typer CLI: `run-pipeline`, `read-cv`, `show-applications`, `web` |
| `src/job_agent/demo_profile.py` | Baked-in demo profile (used when neither `--cv` nor `--profile` is given) |
| `src/job_agent/schemas/` | Pydantic models: `JobPosting`, `UserProfile`, `MatchResult`, `GeneratedApplication`, `ApplicationStatus` |
| `src/job_agent/agents/profiler.py` | **CV Reader** — LLM extracts a `UserProfile` from raw CV text (`prompts/profiler.md`) |
| `src/job_agent/utils/cv.py` | CV text extraction (PDF via pdfplumber / DOCX / TXT / MD) + YAML profile load/save |
| `src/job_agent/agents/scout.py` | CrewAI agent over Adzuna+BA tools; falls back to `_direct_scout` (no LLM) when the agent fails |
| `src/job_agent/agents/demo_scout.py` | Stable offline demo postings (no network/LLM) for presentations |
| `src/job_agent/agents/matcher.py` | Deterministic skill-overlap scorer + optional LLM semantic matcher, with fallback |
| `src/job_agent/agents/writer.py` | Template cover-letter writer + optional LLM writer, with fallback |
| `src/job_agent/agents/tracker.py` | Persists `ApplicationStatus` to SQLite via `Store` |
| `src/job_agent/utils/llm.py` | OpenAI-compatible chat client (ollama/openai/kiconnect/groq); anthropic via CrewAI |
| `src/job_agent/memory/store.py` | SQLite wrapper; three tables (`jobs`, `applications`, `status`) keyed by `job_id` |
| `src/job_agent/memory/profile_index.py` | Optional ChromaDB profile context (`--chroma`); offline hash embeddings |
| `src/job_agent/tools/job_search.py` | Adzuna + BA-Jobsuche HTTP adapters + `search_all` (deterministic multi-board merge) |
| `src/job_agent/web.py` | stdlib browser UI (`web` command); CV upload (PDF/TXT/MD) via `/api/extract-cv`, or paste |
| `src/job_agent/utils/config.py` | Reads `.env`; exposes `settings` singleton with all API keys and paths |

### LLM & framework choices (from ADRs)

- **CrewAI** for agent orchestration (ADR-0002). Tools are `@tool`-decorated functions — `tools/job_search.py` is already shaped for this.
- **Provider is configurable** via `LLM_PROVIDER` (ADR-0003/0004). Supported:
  `ollama` (local), `openai`, `kiconnect` (a hosted OpenAI-compatible gateway),
  `anthropic`, `groq`. No agent hard-codes a provider.
- `openai` and `kiconnect` are OpenAI-compatible and share `OPENAI_API_KEY` +
  `LLM_BASE_URL`. `utils/llm.py` (`call_llm`) issues a plain OpenAI
  Chat-Completions POST for these; `agents/scout.py::_get_llm()` builds the
  matching CrewAI `LLM(model="openai/<model>", base_url=…, api_key=…)`.
- The Profiler, and the LLM matcher/writer, all go through `call_llm`; the
  Scout (CrewAI) goes through `_get_llm`. Both read `settings.llm_*`.

### Environment variables (`.env`)

```
# Provider: ollama | openai | kiconnect | anthropic | groq
LLM_PROVIDER=kiconnect
LLM_MODEL=gpt-4o-mini          # the model id your gateway exposes
LLM_BASE_URL=https://<host>/v1 # required for kiconnect (OpenAI-compatible)
OPENAI_API_KEY=...             # used by openai AND kiconnect
LLM_TEMPERATURE=0.2
LLM_CALL_TIMEOUT=60
ENABLE_LLM_AGENTS=true         # LLM matcher + writer (CV reading always uses the LLM)
ENABLE_CHROMA=false
ADZUNA_APP_ID=...              # Sprint 2 live Scout
ADZUNA_APP_KEY=...
SQLITE_PATH=./data/job_agent.db
CHROMA_PATH=./data/chroma_db
```

See `.env.example` for the full, commented template.

### Sprint status (Sprint 3 — implemented)

Profiler/Scout/Matcher/Writer/Tracker are all implemented. Keep these
signatures stable when editing:

```python
def run_profiler(cv_text: str) -> UserProfile: ...
def run_scout(profile: UserProfile, query: str | None = None, limit: int = 5) -> list[JobPosting]: ...
```

Pitfalls worth remembering:
- LLM output is a raw string — strip Markdown fences before `json.loads`, then
  validate with `model_validate(...)`. `UserProfile` uses `extra = "forbid"`, so
  the Profiler filters to known keys (`_coerce_profile_dict`).
- Every LLM call has a deterministic fallback **except** CV reading, which
  needs the LLM (use `--profile` YAML to stay fully offline).
- Quality gates: `pytest` (offline), `ruff check src tests`, `mypy src` must stay green.
