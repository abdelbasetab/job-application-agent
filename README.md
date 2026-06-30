# Job Application Agent

A multi-agent system for the German student job-search pipeline:
**find -> match -> draft -> track**.

Built as the portfolio project for the *AI Agents & RAG Systems* module
(Westfaelische Hochschule, Prof. Dr. Gleim).

## What It Does

| Agent | Current role |
| --- | --- |
| Profiler | Reads your CV / Lebenslauf (PDF/DOCX/TXT/MD) and extracts a structured profile via the configured LLM |
| Scout | Finds job postings via Adzuna + BA-Jobsuche, with an offline demo scout for stable presentations |
| Matcher | Scores postings with an explainable weighted 1–5 rubric + ghost-job/scam risk check (optional LLM semantics, deterministic fallback) |
| Writer | Drafts German cover letters with optional Sprint-3 LLM generation and template fallback |
| Tracker | Persists jobs, drafted applications, and status records in SQLite; can email applications (SMTP) and sync replies (IMAP) |

All handoffs use typed Pydantic schemas instead of freeform strings.

## Current Status

Sprint 3 is implemented as code, with one important demo distinction:

- Offline demo path is stable and does not need internet, API keys, or Ollama.
- CV reading (`--cv`) extracts your profile via the configured LLM. The default
  provider is **KI-Connect** (an OpenAI-compatible gateway); Ollama, OpenAI,
  Anthropic, and Groq are one `.env` change away.
- Live Scout path is implemented, but depends on external API availability,
  Adzuna credentials, and the configured LLM. It falls back to a direct,
  no-LLM multi-board search if the agent fails.
- Matcher and Writer can use the configured LLM via `--llm-agents`, with
  deterministic fallback if the LLM is unavailable.
- ChromaDB profile context can be enabled via `--chroma`; when
  `EMBEDDING_MODEL` is set it uses the OpenAI-compatible KI-Connect
  `/embeddings` endpoint, otherwise it falls back to local deterministic hash
  vectors.
- The browser UI is a **multi-user web app**: account login, per-user data
  isolation, CSRF protection, rate-limited auth, SQLite schema migrations, and
  a `Dockerfile` + `compose` + CI workflow for deployment (see **Web UI** and
  **Deployment** below).

## Quick Start

```bash
# Install project dependencies
uv pip install -e ".[dev]"

# Run the stable offline demo
python -m job_agent.main run-pipeline --demo --reset-demo-db --query "Werkstudent KI" --limit 5 --threshold 0.5

# Show generated draft applications
python -m job_agent.main show-applications --demo

# Start the local browser UI
python -m job_agent.main web

# Run offline tests
pytest
```

The demo command writes to `./data/demo_job_agent.db` by default, so it does
not mix presentation data with the normal application database.

## Read your CV (Lebenslauf) — KI-Connect / OpenAI

Instead of the baked-in demo profile, point the pipeline at your real CV. The
**Profiler** agent reads the file and uses the configured LLM (an OpenAI model
via **KI-Connect**) to extract a structured profile, then Scout/Matcher/Writer
run against *your* data.

1. Configure the provider in `.env` (copy from `.env.example`):

   ```dotenv
   LLM_PROVIDER=kiconnect
   LLM_MODEL=gpt-4o-mini
   LLM_BASE_URL=https://<your-kiconnect-host>/v1   # OpenAI-compatible, usually ends in /v1
   OPENAI_API_KEY=<your-kiconnect-api-key>
   ENABLE_LLM_AGENTS=true
   ```

2. Inspect what the LLM extracted from your CV (and optionally save it as YAML):

   ```bash
   python -m job_agent.main read-cv --cv data/profile/sample_cv.md
   python -m job_agent.main read-cv --cv path/to/your_cv.pdf --out data/profile/profile.yaml
   ```

3. Run the full pipeline against your CV (live job search + your profile):

   ```bash
   # Real jobs from Adzuna/BA, matched + cover letters written by the LLM
   python -m job_agent.main run-pipeline --cv path/to/your_cv.pdf --llm-agents --query "Werkstudent KI" --limit 5

   # Offline-safe demo jobs, but matched against your real CV
   python -m job_agent.main run-pipeline --demo --reset-demo-db --cv data/profile/sample_cv.md --query "Werkstudent KI"

   # Already have a profile.yaml? Skip the LLM extraction:
   python -m job_agent.main run-pipeline --profile data/profile/profile.yaml --demo --reset-demo-db
   ```

`--cv` accepts **PDF, DOCX, TXT, or Markdown**. If your KI-Connect gateway
cannot do tool-calling, add `--direct` to make Scout query the job boards
directly instead of through the CrewAI agent (the agent also falls back to this
automatically).

## Sprint 3 Features

```bash
# Demo data + LLM matcher/writer + Chroma profile context
python -m job_agent.main run-pipeline --demo --reset-demo-db --llm-agents --chroma --query "Werkstudent KI" --limit 5 --threshold 0.5
```

`--llm-agents` uses the configured `LLM_PROVIDER`/`LLM_MODEL` for semantic
matching and German cover-letter drafting. If the LLM call fails, the pipeline
logs a warning and falls back to the deterministic matcher/template writer.

`--chroma` indexes the profile into ChromaDB at `CHROMA_PATH` and retrieves
relevant profile snippets for the Matcher and Writer. With KI-Connect, set an
embedding model exposed by the gateway, for example:

```dotenv
EMBEDDING_MODEL=Qwen 3 Embedding 8B
```

## Web UI

```bash
python -m job_agent.main web --host 127.0.0.1 --port 7860
# host/port also read from WEB_HOST / WEB_PORT
```

Open `http://127.0.0.1:7860`. The UI is **multi-user**: visitors register or log
in first, and every account gets its own isolated pipeline data (profile, jobs,
applications, tracker) under `data/users/<id>/` — no account can see another's
data. In the **Lebenslauf (CV)** panel you can **import your CV as PDF** (or
TXT/MD) — the file is parsed server-side, the extracted text fills the CV box,
then click **Pipeline**. A ready-to-try sample lives at
`data/profile/sample_cv.pdf`. The Matcher shows an explainable **1–5 scoring
rubric** (weighted dimensions with evidence) and a **ghost-job / scam risk
check** per posting. The server is stdlib-only — no extra web framework.

### Accounts & security

- **Auth:** email + password, hashed with PBKDF2-HMAC-SHA256; sessions are
  random tokens stored only as SHA-256 hashes, in a 7-day `HttpOnly` cookie.
- **Per-user isolation:** all SQLite paths are confined to the requester's own
  `data/users/<id>/` directory; cross-user or traversal paths are rejected.
- **CSRF:** state-changing requests require a double-submit `X-CSRF-Token`
  header matching the `job_agent_csrf` cookie (on top of `SameSite=Lax`).
- **Throttling:** login/registration are rate-limited per IP (and per email).
- **HTTPS:** set `WEB_SECURE_COOKIES=true` when serving behind a TLS proxy so
  cookies carry the `Secure` flag. Misconfiguration is logged at startup.

### Tracker email demo

The Tracker can prepare or send the selected application by email from the Web
UI. The safe default is a dry-run:

```dotenv
EMAIL_DRY_RUN=true
EMAIL_DEMO_RECIPIENT=your-demo-inbox@example.com
```

For real SMTP sending, configure a provider/app password and set:

```dotenv
EMAIL_DRY_RUN=false
EMAIL_SMTP_HOST=smtp.example.com
EMAIL_SMTP_PORT=587
EMAIL_USE_TLS=true
EMAIL_SMTP_USER=your-email@example.com
EMAIL_SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@example.com
```

When a real email is sent, the Tracker marks the application as `submitted`
and stores `submitted_at`. In dry-run mode it records a note but keeps the
status unchanged.

The Tracker can also read replies from your inbox and classify common
application responses:

```dotenv
EMAIL_SYNC_DRY_RUN=true
EMAIL_IMAP_HOST=imap.gmail.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_USER=your-email@gmail.com
EMAIL_IMAP_PASSWORD=your-app-password
EMAIL_IMAP_FOLDER=INBOX
```

Recognized replies are mapped to `submitted`, `interview`, `rejected`, or
`offer`. With `EMAIL_SYNC_DRY_RUN=true`, the UI only shows proposed updates.
Set `EMAIL_SYNC_DRY_RUN=false` after testing to let the Tracker update statuses
automatically.

## Deployment (Docker)

The multi-user server ships with a production `Dockerfile` and `compose` file.
The image runs as a non-root user, persists all data to a `/data` volume, and
has a healthcheck on `/api/auth/me`.

```bash
# Build + run (reads .env if present; persists data in a named volume)
docker compose up --build
# → http://localhost:7860
```

Key deployment env vars (see `.env.example`): `WEB_HOST`, `WEB_PORT`,
`JOB_AGENT_DATA_DIR` (writable data root), and `WEB_SECURE_COOKIES=true` when
running behind HTTPS. Continuous integration (`.github/workflows/ci.yml`) runs
`ruff`, `mypy`, and the full `pytest` suite on every push and pull request.

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
  web.py               Multi-user stdlib web server (auth, CSRF, per-user data)
  web_static/          Browser UI (index.html, app.js, styles.css)
  schemas/             Pydantic contracts between agents
  agents/              scout.py, demo_scout.py, matcher.py, writer.py, tracker.py
  tools/               job_search.py + email_delivery.py / email_sync.py
  memory/              store.py + auth_store.py (SQLite, migrated), profile_index.py
  prompts/             Prompt templates for LLM-backed agents
  utils/               Config and logging

tests/                 Offline unit tests + integration tests
docs/                  ADRs, legal notes, Sprint 1 handoff
data/                  Per-user SQLite stores + auth.db (gitignored)
Dockerfile, docker-compose.yml, .github/workflows/ci.yml
```

## Test Status

Expected offline result:

```bash
pytest
# 92 passed, 3 deselected
```

Integration tests are intentionally separate:

```bash
pytest -m integration
```

They hit real services and may fail when credentials or API access are not
available.
