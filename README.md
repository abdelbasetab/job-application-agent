# Job Application Agent

A multi-agent system that automates the German student job search pipeline:
**find → match → draft → track**.

Built as the portfolio project for the *AI Agents & RAG Systems* module
(Westfälische Hochschule, Prof. Dr. Gleim).

---

## What it does

| Agent       | Role                                                                    |
| ----------- | ----------------------------------------------------------------------- |
| **Scout**   | Discovers relevant job postings (Adzuna + Bundesagentur für Arbeit API) |
| **Matcher** | Scores each posting against the user's profile (skills, prefs, hard reqs) |
| **Writer**  | Drafts a tailored cover letter + CV adjustments for matches above threshold |
| **Tracker** | Persists every application's status (`draft → submitted → interview …`) |

The agents talk to each other through **typed Pydantic schemas** — there is no
"freeform string" handoff. Every transition is validated.

---

## Sprint plan

The project is shipped in 5 weekly sprints:

| Sprint | Goal                                                                          |
| ------ | ----------------------------------------------------------------------------- |
| **1**  | Tracer bullet: schemas + mock agents end-to-end, repo scaffold, ADRs          |
| 2      | Scout: real job-board calls (Adzuna + BA-API), normalization, dedup           |
| 3      | Matcher + Writer: LLM-backed scoring + cover-letter drafting                  |
| 4      | Tracker + memory: SQLite store, ChromaDB embeddings, no-duplicate guard       |
| 5      | UI + demo polish: Streamlit dashboard, evaluation set, final pitch artifacts  |

The current state is **Sprint 1** — see `docs/sprint_1_handoff.md`.

---

## Quick start

The default provider is **local Ollama** — no API keys, no internet
required. See [ADR-0004](docs/adr/0004-llm-provider-local-default.md) for
the rationale (cost, data sovereignty, offline capability).

```bash
# 1. Install Ollama and pull the default model (one-time, ~4 GB)
#    Windows / macOS / Linux: https://ollama.com/download
ollama pull qwen2.5:7b-instruct
ollama serve                       # starts the daemon on http://localhost:11434

# 2. Create a virtual environment
uv venv && source .venv/bin/activate   # or: python -m venv .venv && .venv\Scripts\activate

# 3. Install the project
uv pip install -e ".[dev]"             # or: pip install -e ".[dev]"

# 4. Copy the env template (defaults to Ollama — no keys required)
cp .env.example .env

# 5. Run the end-to-end pipeline
python -m job_agent.main run-pipeline --limit 3 --threshold 0.5

# 6. Run the offline test suite
pytest

# Optional — exercise the real Ollama call (requires `ollama serve`):
pytest -m integration
```

You should see four agents fire in sequence, exchanging Pydantic objects, and
the run ending with a saved `ApplicationStatus` in `data/job_agent.db`.

### Switching providers

Set `LLM_PROVIDER` in `.env` to one of `ollama` (default), `anthropic`, or
`groq`, then set the matching `LLM_MODEL` and API key. No code changes
required.

---

## Repo layout

```
job-application-agent/
├── src/job_agent/
│   ├── main.py              # Typer CLI entrypoint
│   ├── pipeline.py          # Orchestrates the 4-agent flow
│   ├── schemas/             # Pydantic models — the contracts between agents
│   ├── agents/              # scout.py (STUB), matcher.py, writer.py, tracker.py
│   ├── tools/               # job_search.py, file_io.py
│   ├── memory/              # store.py (SQLite), embeddings.py (ChromaDB, Sprint 4)
│   ├── prompts/             # *.md prompt templates
│   └── utils/               # logging, config
├── tests/                   # pytest suite — schemas + tracer bullet
├── data/                    # profile.yaml, scraped jobs, drafted applications
├── docs/
│   ├── adr/                 # Architecture Decision Records
│   ├── legal-notes.md       # ToS / GDPR considerations
│   └── sprint_1_handoff.md  # What's built, what's stubbed, where you plug in Scout
└── scripts/                 # one-shot helper scripts (e.g. seed_profile.py)
```

---

## Tech stack

- **Python 3.11+** with **Pydantic v2** for typed data flow
- **CrewAI** for agent orchestration (other framework options documented in `docs/adr/0002-agent-framework.md`)
- **Local Ollama** as default LLM (`qwen2.5:7b-instruct`); Anthropic / Groq selectable via `LLM_PROVIDER` — see ADR-0003 and ADR-0004
- **SQLite** for state, **ChromaDB** for embeddings
- **Typer** for the CLI, **Rich** for log output

---

## Status: Sprint 1

Working: full project scaffold, all schemas, mock Matcher/Writer/Tracker,
SQLite store, end-to-end tracer bullet, pytest suite, three ADRs.

To do (Sprint 1 close-out): **implement the Scout agent**. See
`docs/sprint_1_handoff.md` for the exact entry point.
