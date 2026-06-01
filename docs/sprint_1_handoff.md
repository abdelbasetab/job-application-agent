# Sprint 1 — Handoff & "Where You Plug In Scout"

This document is the bridge between the scaffold you have *now* and the
Scout agent you will *write* once you finish the DeepLearning.AI CrewAI
tutorial.

---

## TL;DR — what you can already do today

```bash
cd job-application-agent
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest                        # all green
python -m job_agent.main run-pipeline
```

You will see four log sections — Scout (stub), Matcher, Writer, Tracker —
and a Rich table summarizing the three demo jobs that flowed through the
pipeline. A SQLite file `data/job_agent.db` is left on disk.

That's the **tracer bullet**: a thin slice of every layer, end-to-end.
From here, every sprint thickens *one* layer at a time without touching
the others.

---

## What's built (don't touch this in Sprint 1)

| Component | File | State |
| --- | --- | --- |
| Pydantic schemas | `src/job_agent/schemas/` | ✅ final shape — every agent reads/writes these |
| Pipeline orchestration | `src/job_agent/pipeline.py` | ✅ done |
| CLI | `src/job_agent/main.py` | ✅ done |
| Matcher (mock) | `src/job_agent/agents/matcher.py` | ✅ Sprint-1 mock (LLM in Sprint 3) |
| Writer (mock) | `src/job_agent/agents/writer.py` | ✅ Sprint-1 mock (LLM in Sprint 3) |
| Tracker | `src/job_agent/agents/tracker.py` | ✅ real (just wraps SQLite) |
| SQLite store | `src/job_agent/memory/store.py` | ✅ done |
| Job-API adapters | `src/job_agent/tools/job_search.py` | ✅ stubbed signatures, ready for Sprint 2 |
| Logging / config | `src/job_agent/utils/` | ✅ done |
| Prompt templates | `src/job_agent/prompts/*.md` | ✅ Scout prompt ready to drop into CrewAI |
| Tests | `tests/test_*.py` | ✅ 11 tests, all green |
| ADRs | `docs/adr/000{1,2,3}-*.md` | ✅ done |
| Legal notes | `docs/legal-notes.md` | ✅ done |

---

## What you build to close out Sprint 1: the Scout agent

There is **one** file that needs your hands:

> 📌 **`src/job_agent/agents/scout.py`**

Its current body returns three hard-coded `JobPosting` fixtures so the rest
of the pipeline could be wired up before you started. Your job is to
**replace the body of `run_scout()`** with a CrewAI `Agent + Task + Crew`
that returns *real* (or at least "real-shaped") postings.

### Step-by-step, after the tutorial

1. **Re-read the comment block at the top of `agents/scout.py`.** It
   contains a 20-line CrewAI skeleton you can paste in.
2. **Read `prompts/scout.md`.** That's the system prompt you'll feed into
   the CrewAI `Agent.backstory` + `Task.description`.
3. **Don't wire the real APIs yet.** For Sprint 1's close-out, it's fine if
   Scout asks the LLM to *invent* three plausible-looking German job ads
   (with realistic-but-fictional companies). Sprint 2 swaps the LLM
   invention for actual `adzuna_search()` + `ba_jobsuche_search()` calls.
4. **The CrewAI output is a string.** You'll need to JSON-parse it and run
   each entry through `JobPosting.model_validate(...)`. Keep this parse
   step inside `run_scout()` — never let unparsed LLM output leak out.
5. **Keep the function signature identical:**
   ```python
   def run_scout(profile: UserProfile, query: str | None = None, limit: int = 5) -> list[JobPosting]:
   ```
   Nothing else in the codebase needs to change.

### Acceptance criteria for Sprint 1 close-out

- [ ] `pytest` is still green after your changes.
- [ ] `python -m job_agent.main run-pipeline` runs without errors and produces
      ≥ 3 jobs from a *real LLM call*, not the hardcoded fixtures.
- [ ] Every returned `JobPosting` passes schema validation.
- [ ] You can `git diff` the change and see that **only** `agents/scout.py`
      (and possibly `pyproject.toml` if you add a CrewAI version pin) was
      touched.

That last bullet is the magic of the tracer-bullet approach: once schemas
are locked, individual agents become drop-in replacements.

---

## Pitfalls to expect (from teaching this pattern before)

1. **CrewAI loves to wrap your output in Markdown fences.** Strip ```json
   fences before `json.loads`. Pattern:
   ```python
   raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
   ```
2. **`Pydantic.HttpUrl` is strict.** If the LLM returns `example.com` (no
   scheme), validation fails. In the prompt, demand `https://...` URLs.
3. **CrewAI's verbose logs are very loud.** Keep `verbose=True` in dev,
   silence with `verbose=False` once you trust it.
4. **API keys for CrewAI's LLM.** CrewAI defaults to OpenAI unless you
   pass an explicit `llm`. For Anthropic, use:
   ```python
   from crewai import LLM
   llm = LLM(model="anthropic/claude-sonnet-4-6", temperature=0.2)
   ```

---

## What Sprint 2 looks like (so you can see ahead)

1. Real `adzuna_search` + `ba_jobsuche_search` implementations (the function
   bodies in `tools/job_search.py` are already drafted — they just need
   working API keys).
2. Scout's Task description shifts from "invent jobs" to "call these two
   tools, dedup, and return".
3. Add normalization helpers for German salary strings ("50.000 - 70.000 €").
4. Add a "do not re-apply" guard in the Tracker (Sprint 2 deliverable).

You'll get a new handoff doc when Sprint 1 is closed.

---

## Sources you'll want open while writing Scout

- [CrewAI docs — Agents](https://docs.crewai.com/concepts/agents)
- [CrewAI docs — Tasks](https://docs.crewai.com/concepts/tasks)
- [Anthropic — Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)
- Your own `prompts/scout.md` and `schemas/job.py` (the contract).

Good luck — and remember: the goal of Sprint 1 isn't a *good* Scout. It's
a *Scout that runs end-to-end through the pipeline*. Sprint 2 makes it good.
