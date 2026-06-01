# ADR-0004: Switch default LLM provider to local Ollama

- **Status:** Accepted
- **Date:** 2026-05-21
- **Sprint:** 1 (close-out)
- **Supersedes (in part):** [ADR-0003](0003-llm-provider.md)

## Context

ADR-0003 picked Anthropic Claude as the default provider. While developing
the Scout close-out we hit three frictions:

1. **Cost.** Every `pytest` run or pipeline rehearsal billed real Anthropic
   tokens. Iteration on the Scout prompt alone burned non-trivial credit.
2. **Data sovereignty.** The candidate profile we pass to the Scout contains
   personal data (name, email, full CV). Sending it to a hosted US LLM is at
   best a grey area under GDPR and contradicts the privacy stance noted in
   `docs/legal-notes.md`.
3. **Offline capability.** The whole pipeline should run from a laptop on
   the train — both for demos and for the grading rubric, which favours
   reproducible, network-free execution.

## Decision

**Default to Ollama** running locally, with `qwen2.5:7b-instruct` as the
default model. Anthropic and Groq remain first-class alternatives, selected
by a single env variable (`LLM_PROVIDER`).

The provider switch is centralised: agents call `_get_llm()` in
`agents/scout.py`, which inspects `settings.llm_provider` and constructs a
CrewAI `LLM` accordingly. **No agent code hard-codes a provider name.**

## Why

- **Zero per-call cost** during development, tests, and demos.
- **Personal data stays on-device** — relevant for the candidate profile
  that flows through Scout (and, in Sprint 3, through Writer).
- **Tests run offline** — the autouse `stub_scout` fixture in
  `tests/conftest.py` removes the LLM from unit tests, and the
  `integration`-marked test exercises the real Ollama call on demand.
- **`qwen2.5:7b-instruct` is small enough to fit on a developer laptop**
  (~4 GB), instruction-tuned, and competent at returning JSON.

## Consequences

- A new contributor must `ollama pull qwen2.5:7b-instruct` once before the
  tracer bullet works end-to-end. README's Quickstart documents this.
- Switching to Anthropic / Groq is a one-line `.env` change — no code
  edit, no redeploy. ADR-0003's "configurable provider" principle still
  holds; only the default flips.
- The CrewAI LLM is now built lazily (`functools.lru_cache`). Importing
  `agents/scout` no longer attempts any network call.
- Prompt files in `prompts/*.md` should stay provider-neutral. If we hit
  noticeable quality regressions on local models, we may add provider-
  specific prompt variants in Sprint 3 (out of scope here).

## Open follow-ups

- Re-evaluate model choice once Writer (Sprint 3) lands — qwen2.5 may
  produce weaker German cover letters than Claude. Promote `LLM_PROVIDER`
  to `anthropic` for the Writer specifically if benchmarks warrant it.
