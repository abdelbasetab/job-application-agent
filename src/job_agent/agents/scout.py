"""Scout agent — discovers real job postings via Adzuna + BA-Jobsuche.

Sprint 2: Scout no longer fabricates jobs. It exposes the two job-search
APIs as CrewAI tools and asks the LLM to call them, combine, and dedup.

The local LLM (qwen2.5:7b via Ollama) only orchestrates — it MUST NOT
invent postings. If both APIs return empty, run_scout raises so callers
fail loudly instead of silently producing nothing.

CrewAI is imported **lazily** inside the functions that need it: the offline
demo, the deterministic ``--direct`` Scout, and the whole test suite work on
machines where CrewAI is not installed at all. Only the live agent path
(``run_scout`` → ``_run_crew_scout``) touches the heavy dependency.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from job_agent.schemas import JobPosting, UserProfile
from job_agent.tools.job_search import adzuna_search, ba_jobsuche_search, search_all
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

if TYPE_CHECKING:  # only for type hints — never triggers the heavy import
    from crewai import LLM, Agent

log = get_logger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# CrewAI tools — thin wrappers around tools/job_search.py (built lazily)
# ────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _build_tools() -> tuple[Any, Any]:
    """Create the CrewAI tool wrappers on first use (imports crewai)."""
    from crewai.tools import tool

    @tool("adzuna_search")
    def adzuna_tool(query: str, location: str = "Germany", limit: int = 10) -> str:
        """Search Adzuna for open positions in Germany.

        Returns a JSON array of JobPosting objects (may be empty).
        Args:
            query: Free-text search term (e.g. "Werkstudent KI", "Data Engineer").
            location: City or region; defaults to all of Germany.
            limit: Max number of postings to return (1-25).
        """
        postings = adzuna_search(query=query, location=location, limit=limit)
        return json.dumps([p.model_dump(mode="json") for p in postings], default=str)

    @tool("ba_jobsuche_search")
    def ba_tool(query: str, location: str = "", limit: int = 10) -> str:
        """Search the German Bundesagentur für Arbeit Jobbörse.

        Returns a JSON array of JobPosting objects (may be empty).
        Args:
            query: Free-text search term; German preferred.
            location: City name, or empty for nationwide.
            limit: Max number of postings to return (1-25).
        """
        postings = ba_jobsuche_search(query=query, location=location, limit=limit, enrich=True)
        return json.dumps([p.model_dump(mode="json") for p in postings], default=str)

    return adzuna_tool, ba_tool


# ────────────────────────────────────────────────────────────────────────────
# LLM construction
# ────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _get_llm() -> LLM:
    """Build the CrewAI LLM lazily, switching on settings.llm_provider."""
    from crewai import LLM

    provider = settings.llm_provider.lower()
    model = settings.llm_model

    if provider == "ollama":
        base_url = settings.llm_base_url or "http://localhost:11434"
        return LLM(
            model=f"ollama/{model}",
            base_url=base_url,
            temperature=settings.llm_temperature,
        )
    if provider in {"openai", "kiconnect"}:
        # OpenAI-compatible. KI-Connect is a hosted gateway addressed via
        # LLM_BASE_URL; plain OpenAI uses litellm's built-in default.
        kwargs: dict[str, Any] = {
            "model": f"openai/{model}",
            "temperature": settings.llm_temperature,
        }
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
            # litellm also picks these up from the environment — set defensively.
            os.environ.setdefault("OPENAI_API_BASE", settings.llm_base_url)
            os.environ.setdefault("OPENAI_BASE_URL", settings.llm_base_url)
        if settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
            os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
        return LLM(**kwargs)
    if provider == "anthropic":
        return LLM(model=f"anthropic/{model}", temperature=settings.llm_temperature)
    if provider == "groq":
        return LLM(model=f"groq/{model}", temperature=settings.llm_temperature)
    raise ValueError(
        f"Unknown LLM_PROVIDER='{settings.llm_provider}'. "
        "Expected one of: ollama, openai, kiconnect, anthropic, groq."
    )


def _build_scout_agent() -> Agent:
    from crewai import Agent

    adzuna_tool, ba_tool = _build_tools()
    return Agent(
        role="Job Scout",
        goal=(
            "Find real job postings in Germany that match the candidate by "
            "calling the available search tools and combining their results."
        ),
        backstory=(
            "You are a meticulous researcher of the German tech job market. "
            "You ONLY return jobs that came back from one of the tools — you "
            "NEVER invent postings, requirements, or companies. If a tool "
            "returns nothing, report nothing for that source."
        ),
        tools=[adzuna_tool, ba_tool],
        llm=_get_llm(),
        verbose=False,
    )


# ────────────────────────────────────────────────────────────────────────────
# Output parsing & dedup
# ────────────────────────────────────────────────────────────────────────────
def _parse_postings(raw: str) -> list[dict[str, Any]]:
    """Strip Markdown fences, JSON-parse, unwrap common envelope keys."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("[scout] JSON parse error: %s\nRaw output:\n%s", exc, raw[:500])
        return []
    if isinstance(data, dict):
        for key in ("jobs", "postings", "data", "results"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
    return data if isinstance(data, list) else []


def _dedup(postings: list[JobPosting]) -> list[JobPosting]:
    """Stable-order dedup by JobPosting.id."""
    seen: set[str] = set()
    out: list[JobPosting] = []
    for p in postings:
        if p.id in seen:
            continue
        seen.add(p.id)
        out.append(p)
    return out


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
def _direct_scout(
    profile: UserProfile, query: str | None = None, limit: int = 5
) -> list[JobPosting]:
    """Deterministic Scout: query both boards directly, no LLM or tool-calling.

    Used as the fallback when the CrewAI agent fails or the configured gateway
    cannot do function-calling. Also reachable directly via ``--direct``.
    """
    search_hint = query or " ".join(profile.skills[:3])
    extra = [skill for skill in profile.skills[:3] if skill]
    postings = search_all(
        query=search_hint,
        location="Germany",
        limit=max(limit, 5),
        extra_queries=extra,
        adzuna_pages=2,
        enrich=True,
    )
    return postings[:limit]


def run_scout(
    profile: UserProfile, query: str | None = None, limit: int = 5
) -> list[JobPosting]:
    """Discover real job postings for the candidate via CrewAI + tools.

    Args:
        profile: Candidate's structured profile.
        query: Optional free-text search hint (falls back to top-3 skills).
        limit: Max postings to return after dedup.

    Returns:
        Validated, deduplicated JobPosting list (length ≤ limit).

    Raises:
        RuntimeError: when both job sources fail or return nothing usable.
    """
    log.info(
        "[scout] start profile=%s provider=%s model=%s limit=%d",
        profile.name,
        settings.llm_provider,
        settings.llm_model,
        limit,
    )

    postings: list[JobPosting] = []
    try:
        postings = _run_crew_scout(profile, query, limit)
    except Exception as exc:
        # Covers LLM/agent init failures (e.g. a model id litellm can't load),
        # a missing crewai install, tool-calling not supported, or kickoff
        # errors. Live search still works below.
        log.warning(
            "[scout] CrewAI agent unavailable (%s) — using direct API search instead",
            exc,
        )

    if not postings:
        log.info("[scout] falling back to deterministic multi-board search")
        postings = _direct_scout(profile, query, limit)

    if not postings:
        raise RuntimeError(
            "Scout produced no postings — both Adzuna and BA-Jobsuche returned "
            "empty or unusable results. Check API credentials and network."
        )

    return postings[:limit]


def _run_crew_scout(
    profile: UserProfile, query: str | None = None, limit: int = 5
) -> list[JobPosting]:
    """Run the CrewAI agent (LLM orchestrates the search tools). May raise."""
    from crewai import Crew, Task

    scout_agent = _build_scout_agent()
    search_hint = query or " ".join(profile.skills[:3])
    per_source = max(limit, 5)

    task = Task(
        description=(
            f"Find up to {limit} open job postings for this candidate in Germany.\n"
            f"Candidate profile (JSON):\n{{profile_json}}\n\n"
            f"Suggested search query: '{search_hint}'\n\n"
            "Process:\n"
            f"1. Call adzuna_search(query='{search_hint}', "
            f"location='Germany', limit={per_source}).\n"
            f"2. Call ba_jobsuche_search(query='{search_hint}', "
            f"location='', limit={per_source}).\n"
            "3. Combine the JSON arrays from both calls.\n"
            "4. Remove duplicates by the 'id' field.\n"
            f"5. Return the first {limit} entries as a JSON array.\n\n"
            "Rules:\n"
            "- Output ONLY the raw JSON array — no Markdown, no commentary.\n"
            "- Each entry MUST come from a tool result. Never invent postings.\n"
            "- Preserve every field from the tool output exactly as returned."
        ),
        expected_output=(
            f"A JSON array of at most {limit} JobPosting objects, taken "
            "verbatim from the search tool results."
        ),
        agent=scout_agent,
    )

    crew = Crew(agents=[scout_agent], tasks=[task], verbose=False)
    crew_output = crew.kickoff(inputs={"profile_json": profile.model_dump_json()})
    raw_items = _parse_postings(crew_output.raw)  # type: ignore[union-attr]
    postings: list[JobPosting] = []
    for item in raw_items:
        try:
            postings.append(JobPosting.model_validate(item))
        except Exception as exc:
            log.warning("[scout] dropping invalid posting from LLM output: %s", exc)
    postings = _dedup(postings)
    log.info("[scout] agent validated %d postings", len(postings))
    return postings
