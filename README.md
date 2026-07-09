# Job Application Agent

A multi-agent system for the German student job-search pipeline:
**find -> match -> draft -> track**.

Built as the portfolio project for the *AI Agents & RAG Systems* module
(Westfaelische Hochschule, Prof. Dr. Gleim). Architecture overview (German):
[ARCHITECTURE.md](ARCHITECTURE.md).

## What It Does

| Agent | Current role |
| --- | --- |
| Profiler | Reads your CV / Lebenslauf (PDF/DOCX/TXT/MD) and extracts a structured profile via the configured LLM (structured outputs) |
| Scout | Finds job postings via Adzuna + BA-Jobsuche, with an offline demo scout for stable presentations |
| Matcher | Three-tier skill matching (alias → similarity → LLM) scored with an explainable weighted 1–5 rubric + ghost-job/scam risk check; LLM calls run in parallel with deterministic fallback |
| Writer | Drafts German cover letters; the LLM path validates its own quality checks and runs one bounded self-correction pass, with template fallback |
| Tracker | Persists jobs, applications, and status in SQLite; emails applications (SMTP), syncs replies (IMAP), and surfaces due follow-ups with ready-to-send drafts |
| CV Reviewer | Rates the CV itself (contact, structure, skills, concreteness, languages, length) with an explainable rubric + concrete German tips |

All handoffs use typed Pydantic schemas instead of freeform strings, and the
Matcher's quality is *measured* against a labeled golden set (`job-agent eval`).

## Current Status

Sprint 4 is implemented as code, with one important demo distinction:

- Offline demo path is stable and does not need internet, API keys, or Ollama.
- CV reading (`--cv`) extracts your profile via the configured LLM. The default
  provider is **KI-Connect** (an OpenAI-compatible gateway); Ollama, OpenAI,
  Anthropic, and Groq are one `.env` change away. All LLM calls get bounded
  retries with backoff, latency/token telemetry, and OpenAI structured
  outputs (with transparent fallback for gateways that reject them).
- Live Scout path is implemented, but depends on external API availability,
  Adzuna credentials, and the configured LLM. It falls back to a direct,
  no-LLM multi-board search if the agent fails — and CrewAI is imported
  lazily, so the offline demo and tests run without it installed.
- Matcher and Writer can use the configured LLM via `--llm-agents`, with
  deterministic fallback if the LLM is unavailable.
- ChromaDB profile context can be enabled via `--chroma`; when
  `EMBEDDING_MODEL` is set it uses the OpenAI-compatible KI-Connect
  `/embeddings` endpoint (also powering tier-2 semantic skill matching),
  otherwise it falls back to local deterministic hash vectors.
- The browser UI is a **multi-user web app**: account login, per-user data
  isolation, CSRF protection, rate-limited auth, SQLite schema migrations, and
  a `Dockerfile` + `compose` + CI workflow for deployment (see **Web UI** and
  **Deployment** below). The dashboard includes an explainable score
  breakdown, a CV-Check panel, and a follow-up radar.

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

# Rate a CV (offline, explainable rubric + tips)
python -m job_agent.main review-cv --cv data/profile/sample_cv.md

# Measure matcher quality against the labeled golden set (offline)
python -m job_agent.main eval

# Show submitted applications that are due for a follow-up
python -m job_agent.main follow-ups --demo

# Evaluate a pasted job ad end-to-end (single-job auto-pipeline)
python -m job_agent.main evaluate-jd --file jd.txt --title "Werkstudent KI" --demo

# Tracker pattern analysis (funnel, response rates, stale applications)
python -m job_agent.main patterns --demo

# Interview guide for an evaluated job
python -m job_agent.main interview-prep --job-id <id> --demo

# Run offline tests
pytest
```

The demo command writes to `./data/demo_job_agent.db` by default, so it does
not mix presentation data with the normal application database.

## Production Checklist

1. Copy `.env.example` to `.env` and fill in the provider, job-board, and email values you actually use.
2. Run `python -m job_agent.main doctor` and fix every `FAIL` before you start the app.
3. Start the UI with `python -m job_agent.main web` for local use or `docker compose up --build` for the container path.
4. Register a fresh account in the UI, then import your CV and connect Gmail/IMAP if you want inbox sync.
5. Keep `data/` out of version control. It is runtime state only and can be deleted to reset the app.

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

## Sprint 4 Features — Eval, CV-Check, Follow-ups

**Measured matcher quality.** `job-agent eval` scores a labeled golden set of
24 postings (strong/good/maybe/skip, incl. deliberate borderline cases) and
reports accuracy, within-one agreement, Cohen's kappa, Spearman correlation,
apply precision/recall at the threshold, and the writer's quality-check pass
rate. With `--llm` it additionally compares the LLM matcher against the
deterministic rubric (agreement, kappa, mean score delta), and `--chroma`
adds a RAG-context ablation. `--json-out data/eval_report.json` saves the
report; `tests/test_evaluation.py` runs the same bounds as a CI regression
gate. LLM telemetry (calls, retries, latency, tokens) is included.

```bash
python -m job_agent.main eval                 # offline, deterministic
python -m job_agent.main eval --llm --chroma  # + LLM comparison + RAG ablation
```

Current deterministic baseline on the golden set (24 cases):

| Metric | Value |
| --- | ---: |
| Accuracy (exact recommendation) | 91.7 % |
| Within-one bucket | 100 % |
| Cohen's kappa | 0.89 |
| Spearman (score vs. label) | 0.96 |
| Apply precision / recall @ 0.6 | 100 % / 100 % |
| Writer quality-check pass rate | 100 % |

The two remaining misses are the documented deliberate borderline cases
(perfect skill match in the wrong city / with an implausible salary), where
the rubric says "strong" and a human says "good".

**CV-Check (Lebenslauf bewerten).** `job-agent review-cv --cv <file>` rates
the CV itself on six weighted dimensions (contact data, structure, skills,
concreteness, languages, length), each with evidence, plus concrete German
improvement tips — fully offline; `--llm` adds a short feedback paragraph
from the configured LLM. The same check lives in the web UI as a gauge panel.

**Follow-up radar.** Submitted applications without activity for N days
(default 7) surface in `job-agent follow-ups` and in the web UI's
*Follow-ups* view — each with a polite, ready-to-send German follow-up draft.
Sending uses the same dry-run-first email stack as applications; recording a
follow-up resets the cadence clock via the status notes.

```bash
python -m job_agent.main follow-ups --demo          # list due follow-ups
python -m job_agent.main follow-ups --demo --mark <job_id>
```

## Sprint 5 Features — Inbox, Muster, Reports, Interview-Prep

**URL-Inbox & paste-a-JD.** Collect job links any time (`inbox` view or
`job-agent inbox --add <url>`) and evaluate them later. Pasting a complete ad
into the *Anzeige einfügen* form runs a single-job auto-pipeline: the text
becomes a validated `JobPosting` (conservative requirement extraction —
bullets under a requirements header first, never invented), gets the full
rubric + ghost-job check, and a cover letter is drafted when the score clears
the threshold. CLI: `job-agent evaluate-jd --file jd.txt --title "…"`.

**Pattern analysis.** `job-agent patterns` (and the *Muster & Statistik*
panel) aggregates the tracker: funnel per status, response/interview rates,
average days-to-response, applications waiting ≥ 14 days, top companies and
sources — with honest German takeaways. Fully offline.

**Markdown evaluation report.** One click ("Report (MD)") writes a
self-contained `bewertungsreport.md` per job — posting facts, the explainable
rubric with evidence, ghost-job flags, the letter draft with its quality
checks, status history and liveness — ideal for archiving or sharing.

**Tailored CV export.** The PDF export now reorders the skills section so
matched skills come first and adds a per-application focus line — reordering
only, never invention.

**Interview prep (light).** Per job, a deterministic guide: STAR-ready
questions for your matched skills, honest strategies for missing ones,
behavioral questions and good questions to ask back — optionally enriched
with ad-specific questions from the LLM. `job-agent interview-prep --job-id …`
or the *Interview-Vorbereitung* button in the job detail view.

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
check** per posting. The **CV-Check** panel rates the Lebenslauf itself
(gauge + rubric + tips), and the **Follow-up radar** lists submitted
applications that have gone quiet, with a one-click (dry-run) follow-up
email. The server is stdlib-only — no extra web framework.

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

The Web UI can also store local SMTP/IMAP credentials per account under the
settings page (Einstellungen). Secrets are kept in the local data directory, not in the CV. The
CV email is used as an identity hint and compared against the sender and IMAP
user so mismatches are visible before sending.

Autonomous follow-up sending is off by default. The Follow-up Radar can run one
safe Autopilot pass that syncs the inbox and prepares due follow-up actions. It
only sends real follow-up emails when both real SMTP sending is enabled and this
flag is set:

```dotenv
EMAIL_AUTO_FOLLOW_UP_SEND=false
EMAIL_AUTOPILOT_INTERVAL_MINUTES=15
```

For Gmail/Outlook OAuth, create an OAuth app with this local redirect URL and
set the matching provider credentials:

```dotenv
EMAIL_OAUTH_REDIRECT_BASE=http://127.0.0.1:7860
EMAIL_OAUTH_GOOGLE_CLIENT_ID=
EMAIL_OAUTH_GOOGLE_CLIENT_SECRET=
EMAIL_OAUTH_MICROSOFT_CLIENT_ID=
EMAIL_OAUTH_MICROSOFT_CLIENT_SECRET=
```

After that, use the settings page's "Gmail verbinden" or "Outlook verbinden"
buttons. OAuth accounts use XOAUTH2 for SMTP/IMAP and tokens are stored in the
local encrypted credential store (design rationale: ADR-0007).

The Autopilot follows a deliberate two-step principle: scheduled passes sync
the inbox and *prepare* due follow-ups; actually sending them stays behind the
explicit double opt-in above (`EMAIL_DRY_RUN=false` **and**
`EMAIL_AUTO_FOLLOW_UP_SEND=true`). Every pass is written to the per-user email
audit log, and the schedule intentionally lives in the server process only.

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

## Local power tools

For private local use the tool ships three operator features:

- **Readiness check** — `job-agent doctor` reports OK / WARN / FAIL for the data
  dir, SQLite stores, LLM/email config, and optional binaries (Tesseract OCR,
  Playwright, the `fpdf2` PDF writer), each with a concrete fix. Non-zero exit
  on any FAIL, so it scripts cleanly.
- **Job liveness** — per posting, a one-shot HTTP check (status / redirect /
  "no longer available" text, German + English) flags **offen / unsicher /
  abgelaufen** in the job detail; an optional Playwright fallback
  (`LIVENESS_DEEP=true`) inspects the rendered page. Never crawls, never crashes
  on a block/timeout. Results are cached per job.
- **PDF export package** — the **Export (PDF)** button renders a formal German
  `anschreiben.pdf` + `lebenslauf.pdf` + `job_snapshot.json`, zipped into
  `data/users/<id>/output/<job>/` and offered as a download.

The boundary between system code and your local data (what an update may replace
vs. what it must never touch) is documented in
[DATA_CONTRACT.md](DATA_CONTRACT.md).

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
  main.py              Typer CLI (run-pipeline, eval, review-cv, follow-ups, web, doctor, …)
  pipeline.py          Orchestrates Scout -> Matcher -> Writer -> Tracker
  web.py               Multi-user stdlib web server (auth, CSRF, per-user data)
  web_static/          Browser UI (dashboard, CV-Check, follow-up radar)
  schemas/             Pydantic contracts between agents (incl. CVAssessment, FollowUpItem)
  agents/              scout, demo_scout, matcher, writer, tracker, profiler, cv_reviewer, interview_prep
  evaluation/          Golden set + metrics for `job-agent eval`
  tools/               job_search, inbox, patterns, report, export, liveness,
                       email_delivery / email_sync / email_account / email_oauth, recipient_extraction
  memory/              store.py + auth_store.py (SQLite, migrated), profile_index.py
  prompts/             Prompt templates for LLM-backed agents
  utils/               llm (retry/telemetry/structured outputs), cv, config, doctor, logging

tests/                 Offline unit tests + integration tests
docs/                  ADRs (incl. 0006 scoring rubric), legal notes, sprint handoffs
data/                  Per-user SQLite stores + auth.db (gitignored)
ARCHITECTURE.md        Komponenten- und Datenfluss-Übersicht (deutsch)
Dockerfile, docker-compose.yml, .github/workflows/ci.yml
```

## Test Status

The offline suite must pass completely (no network, no LLM, no CrewAI
install required); CI additionally enforces `ruff`, `mypy --strict`, a
coverage floor, and a Docker image build:

```bash
pytest
ruff check src tests
mypy src
```

Integration tests are intentionally separate:

```bash
pytest -m integration
```

They hit real services and may fail when credentials or API access are not
available.

## Runtime Data

The repository should stay clean after a production push. Source code, docs,
and templates live in git. Runtime state lives in `data/`, per-user output
folders, and local log files. If you need a full reset, delete `data/` and start
the app again; the application will recreate empty stores on demand.
