# ADR-0002: Use CrewAI for Agent Orchestration

- **Status:** Accepted
- **Date:** 2026-05-11
- **Sprint:** 1

## Context

We need to coordinate four agents (Scout, Matcher, Writer, Tracker) that pass
typed messages and occasionally call external tools. The candidate frameworks:

| Framework | Pros | Cons |
| --- | --- | --- |
| **CrewAI** | Role-first model, simple `Agent` / `Task` / `Crew` API, German-language docs in tutorial | Younger ecosystem, fewer integrations |
| **LangGraph** | Powerful state-graph model, mature LangChain ecosystem | Heavier, steeper learning curve |
| **AutoGen** | Strong multi-agent chat patterns | Conversation-centric, awkward for our pipeline |
| **No framework** (plain Python) | Zero magic | We'd reinvent role/tool wiring |

## Decision

**Use CrewAI** for Scout (and for any agent that grows beyond a single
deterministic function). Matcher, Writer, and Tracker stay as plain Python
in Sprint 1 because LLM-backed logic doesn't arrive until Sprint 3.

## Why

1. The DeepLearning.AI CrewAI course is part of the learning roadmap — using
   the same framework keeps tutorial → project transfer friction low.
2. CrewAI's role / goal / backstory framing maps cleanly to our four agents.
3. Tools in CrewAI are just `@tool`-decorated functions — `tools/job_search.py`
   is already shaped for this.
4. The framework is **swappable**: the Pydantic schemas are the real contract,
   so a future migration to LangGraph would only rewrite the agent files.

## Consequences

- Add `crewai` and `crewai-tools` to `pyproject.toml`.
- The Scout module is structured as a CrewAI `Agent + Task + Crew` (see the
  template comment in `agents/scout.py`).
- LLM provider is set on the Agent (`llm=...`). Provider choice is governed
  by ADR-0003.
