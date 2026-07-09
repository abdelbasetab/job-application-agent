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

# Sprint 4: measure matcher quality, rate a CV, list due follow-ups (all offline)
python -m job_agent.main eval
python -m job_agent.main review-cv --cv data/profile/sample_cv.md
python -m job_agent.main follow-ups --demo

# Sprint 5: URL inbox, paste-a-JD evaluation, tracker patterns, interview prep
python -m job_agent.main inbox --add https://example.de/jobs/1
python -m job_agent.main evaluate-jd --file jd.txt --title "Werkstudent KI" --demo
python -m job_agent.main patterns --demo
python -m job_agent.main interview-prep --job-id <id> --demo

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
| `src/job_agent/main.py` | Typer CLI: `run-pipeline`, `read-cv`, `eval`, `review-cv`, `follow-ups`, `show-applications`, `web`, `doctor` |
| `src/job_agent/demo_profile.py` | Baked-in demo profile (used when neither `--cv` nor `--profile` is given) |
| `src/job_agent/schemas/` | Pydantic models: `JobPosting`, `UserProfile`, `MatchResult`, `GeneratedApplication`, `ApplicationStatus`, `CVAssessment`, `FollowUpItem` |
| `src/job_agent/agents/profiler.py` | **CV Reader** — LLM extracts a `UserProfile` from raw CV text (`prompts/profiler.md`) |
| `src/job_agent/agents/cv_reviewer.py` | **CV-Check** — deterministic 6-dimension CV quality rubric + optional LLM feedback |
| `src/job_agent/evaluation/` | Golden-set eval harness (`harness.py`, `golden_set.yaml`) behind `job-agent eval` |
| `src/job_agent/utils/cv.py` | CV text extraction (PDF via pdfplumber / DOCX / TXT / MD) + YAML profile load/save |
| `src/job_agent/agents/scout.py` | CrewAI agent over Adzuna+BA tools (CrewAI imported lazily); falls back to `_direct_scout` (no LLM) |
| `src/job_agent/agents/demo_scout.py` | Stable offline demo postings (no network/LLM) for presentations |
| `src/job_agent/agents/matcher.py` | 3-tier skill matching (alias → similarity → LLM) + weighted rubric score (ADR-0006), parallel LLM calls, fallback |
| `src/job_agent/agents/writer.py` | Template cover-letter writer + LLM writer with one bounded self-correction pass |
| `src/job_agent/agents/tracker.py` | Persists `ApplicationStatus` to SQLite via `Store`; follow-up cadence (`due_follow_ups`, `record_follow_up`) |
| `src/job_agent/agents/interview_prep.py` | Per-job interview guide (deterministic core, optional LLM extras) |
| `src/job_agent/tools/inbox.py` | URL inbox + paste-a-JD single-job auto-pipeline (`posting_from_text`, `evaluate_pasted_job`) |
| `src/job_agent/tools/patterns.py` | Tracker pattern analysis (funnel, response rates, stale applications) |
| `src/job_agent/tools/report.py` | Per-job Markdown evaluation report (`bewertungsreport.md`) |
| `src/job_agent/tools/email_account.py` + `email_oauth.py` | Per-user email accounts (SMTP/IMAP, Gmail/Microsoft OAuth with refresh) |
| `src/job_agent/memory/credential_store.py` | Encrypted local secret storage (stdlib crypto, see ADR-0007) |
| `src/job_agent/tools/recipient_extraction.py` | Conservative application-address extraction from postings |
| `src/job_agent/utils/llm.py` | OpenAI-compatible chat client with retries/backoff, telemetry, structured outputs; anthropic via CrewAI |
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

### Sprint status (Sprint 4 — implemented)

Profiler/Scout/Matcher/Writer/Tracker/CV-Reviewer plus the eval harness are
implemented. Keep these signatures stable when editing:

```python
def run_profiler(cv_text: str) -> UserProfile: ...
def run_scout(profile: UserProfile, query: str | None = None, limit: int = 5) -> list[JobPosting]: ...
def run_cv_reviewer(cv_text: str, profile: UserProfile | None = None, use_llm: bool | None = None) -> CVAssessment: ...
def due_follow_ups(store: Store, days: int = 7, candidate_name: str = "", now: datetime | None = None) -> list[FollowUpItem]: ...
```

Pitfalls worth remembering:
- LLM output is a raw string — strip Markdown fences before `json.loads`, then
  validate with `model_validate(...)`. `UserProfile` uses `extra = "forbid"`, so
  the Profiler filters to known keys (`_coerce_profile_dict`). `call_llm` can
  additionally request structured outputs (`schema=SomeModel`), but gateways
  may reject `response_format` — the fallback path (plain completion + tolerant
  parsing) must stay intact.
- Every LLM call has a deterministic fallback **except** CV reading, which
  needs the LLM (use `--profile` YAML to stay fully offline).
- The Matcher score is the weighted rubric (ADR-0006): hard gate at 0 covered
  must-haves, level-mismatch cap at 0.55, risk penalties on top. Changing
  weights? Run `job-agent eval` — `tests/test_evaluation.py` enforces the
  golden-set bounds in CI.
- CrewAI is imported lazily in `agents/scout.py`; never re-introduce a
  module-level `import crewai`, or the offline suite breaks on machines
  without it.
- Quality gates: `pytest` (offline), `ruff check src tests`, `mypy src`, and
  the CI coverage floor must stay green.
