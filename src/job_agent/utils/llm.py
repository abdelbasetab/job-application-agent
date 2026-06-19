"""Small LLM helper for the Profiler / Matcher / Writer text calls.

Most providers we support speak the OpenAI Chat-Completions protocol:

- **ollama**     — local, OpenAI-compatible endpoint at ``/v1/chat/completions``
- **openai**     — OpenAI cloud
- **kiconnect**  — a hosted OpenAI-compatible gateway (e.g. the university's
                   "KI-Connect"); set ``LLM_BASE_URL`` + ``OPENAI_API_KEY``
- **groq**       — OpenAI-compatible cloud

For all of those we issue a single plain ``httpx`` POST so the helper has no
hard dependency on litellm/CrewAI. ``anthropic`` is the one non-OpenAI shape;
it is routed through the existing CrewAI ``LLM`` adapter.
"""

from __future__ import annotations

from typing import Any

import httpx

from job_agent.utils.config import settings

# Providers that speak the OpenAI Chat-Completions protocol.
_OPENAI_COMPATIBLE = {"ollama", "openai", "kiconnect", "groq"}

# Sensible default endpoints when LLM_BASE_URL is not set.
_DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    # kiconnect has no public default — it MUST be configured via LLM_BASE_URL.
}


def chat_completions_url(base_url: str) -> str:
    """Normalize any base URL into a full ``/chat/completions`` endpoint.

    Handles the common variants so users can paste whatever their gateway
    documents:
        http://localhost:11434              -> .../v1/chat/completions
        https://host/v1                     -> .../v1/chat/completions
        https://host/v1/chat/completions    -> unchanged
    """
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1") or "/v1/" in base or base.endswith("/openai/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _openai_compatible_chat(messages: list[dict[str, str]]) -> str:
    provider = settings.llm_provider.lower()
    base = settings.llm_base_url or _DEFAULT_BASE_URLS.get(provider)
    if not base:
        raise RuntimeError(
            f"LLM_PROVIDER='{settings.llm_provider}' needs LLM_BASE_URL to be set "
            "(e.g. your KI-Connect endpoint like https://.../v1)."
        )

    headers = {"Content-Type": "application/json"}
    key = settings.llm_api_key
    if key:
        headers["Authorization"] = f"Bearer {key}"

    response = httpx.post(
        chat_completions_url(base),
        json={
            "model": settings.llm_model,
            "messages": messages,
            "temperature": settings.llm_temperature,
            "stream": False,
        },
        headers=headers,
        timeout=settings.llm_call_timeout,
    )
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return str(data["choices"][0]["message"]["content"])


def call_llm(messages: list[dict[str, str]]) -> str:
    """Call the configured LLM and return plain text."""
    if settings.llm_provider.lower() in _OPENAI_COMPATIBLE:
        return _openai_compatible_chat(messages)

    # anthropic (or anything else CrewAI/litellm can route) via the CrewAI adapter.
    from job_agent.agents.scout import _get_llm

    raw = _get_llm().call(messages=messages)  # type: ignore[arg-type]
    if not isinstance(raw, str):
        return str(raw)
    return raw
