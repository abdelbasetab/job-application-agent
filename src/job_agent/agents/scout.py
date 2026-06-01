"""Scout agent — discovers and normalizes job postings.

Sprint 1 close-out: the Scout asks the configured LLM to invent realistic-but-
fictional German job postings. Sprint 2 wires the real Adzuna and BA-Jobsuche
tools in their place. The function signature is the only stable contract.

The CrewAI LLM is built lazily via ``_get_llm()`` so importing this module does
not require network access (important for offline pytest runs).
"""

from __future__ import annotations

import json
from functools import lru_cache

from crewai import LLM, Agent, Crew, Task

from job_agent.schemas import JobPosting, UserProfile
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_llm() -> LLM:
    """Build the CrewAI LLM lazily, switching on settings.llm_provider."""
    provider = settings.llm_provider.lower()
    model = settings.llm_model

    if provider == "ollama":
        base_url = settings.llm_base_url or "http://localhost:11434"
        return LLM(
            model=f"ollama/{model}",
            base_url=base_url,
            temperature=settings.llm_temperature,
        )
    if provider == "anthropic":
        return LLM(
            model=f"anthropic/{model}",
            temperature=settings.llm_temperature,
        )
    if provider == "groq":
        return LLM(
            model=f"groq/{model}",
            temperature=settings.llm_temperature,
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER='{settings.llm_provider}'. "
        "Expected one of: ollama, anthropic, groq."
    )


def _build_scout_agent() -> Agent:
    return Agent(
        role="Job Scout",
        goal=(
            "Find job postings in Germany that match the candidate's skills, "
            "preferred locations, and employment type."
        ),
        backstory=(
            "You are a meticulous researcher of the German tech job market. "
            "You know Werkstudent, Praktikum, and junior roles well. "
            "You NEVER invent skill requirements — if the source doesn't list it, "
            "it does not go into 'requirements'. An empty list is better than a wrong one."
        ),
        llm=_get_llm(),
        verbose=False,
    )


def run_scout(profile: UserProfile, query: str | None = None, limit: int = 5) -> list[JobPosting]:
    """Discover job postings for a given profile using a CrewAI agent.

    Args:
        profile: The candidate's structured profile.
        query: Optional free-text search hint (e.g. "Werkstudent KI Berlin").
        limit: Max number of postings to return.

    Returns:
        A list of validated JobPosting objects (max `limit`).
    """
    log.info(
        "[scout] starting CrewAI run profile=%s provider=%s model=%s limit=%d",
        profile.name,
        settings.llm_provider,
        settings.llm_model,
        limit,
    )

    scout_agent = _build_scout_agent()
    search_hint = f" Use the search hint: '{query}'." if query else ""
    task = Task(
        description=(
            f"Create {limit} realistic German tech job postings that match this candidate.\n"
            f"Candidate profile (JSON):\n{{profile_json}}\n"
            f"{search_hint}\n\n"
            "Rules:\n"
            "- Jobs must be in Germany (or remote from DE).\n"
            "- Employment types must fit the candidate's preferences.\n"
            "- Use realistic German company names and real German cities.\n"
            "- Each posting's 'id' must be a unique string like 'scout-001', 'scout-002', etc.\n"
            "- Set 'source' to 'manual' and 'source_id' equal to 'id'.\n"
            "- ALL urls must start with 'https://'.\n"
            "- 'requirements' and 'nice_to_have' must be lowercase strings.\n"
            "- Do NOT invent requirements that aren't in your description.\n\n"
            "Output: a JSON array (no markdown, no explanation) — only the raw JSON array."
        ),
        expected_output=(
            f"A JSON array of exactly {limit} objects, each matching this schema:\n"
            "{\n"
            '  "id": "scout-001",\n'
            '  "source": "manual",\n'
            '  "source_id": "scout-001",\n'
            '  "url": "https://example-company.de/jobs/123",\n'
            '  "title": "Werkstudent KI (m/w/d)",\n'
            '  "company": "Beispiel GmbH",\n'
            '  "location": "Dortmund",\n'
            '  "description": "...",\n'
            '  "requirements_raw": "Python, Git",\n'
            '  "requirements": ["python", "git"],\n'
            '  "nice_to_have": ["docker"],\n'
            '  "employment_type": "working-student",\n'
            '  "remote": false\n'
            "}"
        ),
        agent=scout_agent,
    )

    crew = Crew(agents=[scout_agent], tasks=[task], verbose=False)
    crew_output = crew.kickoff(inputs={"profile_json": profile.model_dump_json()})
    raw: str = crew_output.raw

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    # Some local LLMs wrap the array in an object like {"jobs": [...]}.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("[scout] JSON parse error: %s\nRaw output:\n%s", exc, raw)
        raise

    if isinstance(data, dict):
        for key in ("jobs", "postings", "data", "results"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break

    if not isinstance(data, list):
        raise ValueError(f"[scout] expected a JSON array, got {type(data).__name__}")

    postings = [JobPosting.model_validate(item) for item in data]
    log.info("[scout] validated %d postings", len(postings))
    return postings[:limit]
