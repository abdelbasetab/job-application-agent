# ADR-0003: Default LLM Provider — Anthropic Claude

- **Status:** Superseded in part by [ADR-0004](0004-llm-provider-local-default.md) (2026-05-21)
- **Date:** 2026-05-11
- **Sprint:** 1

> **Note (2026-05-21):** The default provider is now local Ollama. The
> configurable-provider principle below still holds; only the default
> flipped. See ADR-0004 for rationale.

## Context

The Matcher (Sprint 3) and Writer (Sprint 3) need an LLM. The Scout agent
needs one for query-planning and requirement extraction. We need to pick a
*default* without locking ourselves in.

## Decision

**Default to Anthropic Claude** (`claude-sonnet-4-6` for general work,
`claude-haiku-4-5` for cheap calls like skill-extraction).

The provider is **configurable** via `LLM_MODEL` in `.env`. The agent code
imports the model from `utils.config.settings` — never hard-codes it.

## Why

1. Claude Sonnet handles German cover-letter drafting with very few
   "Englisch-Anglizismen" leakage in our experiments.
2. Tool-calling reliability is high — important for Scout.
3. Anthropic has a generous free-tier / student credit, useful while the
   project is unfunded.
4. The Anthropic Python SDK is stable and well-documented.

OpenAI's `gpt-4o-mini` is kept as a fallback for cost-sensitive batch work
(e.g. evaluating 100 job postings during Sprint 5).

## Consequences

- `ANTHROPIC_API_KEY` is the only LLM-related secret required for Sprints 2-3.
- All prompt files (`prompts/*.md`) target Claude's instruction style
  (XML-ish tags, explicit constraints).
- If we ever need to swap providers, the change is contained to the agent
  modules — schemas, pipeline, tracker stay untouched.
