"""LLM helper for the Profiler / Matcher / Writer text calls.

Most providers we support speak the OpenAI Chat-Completions protocol:

- **ollama**     — local, OpenAI-compatible endpoint at ``/v1/chat/completions``
- **openai**     — OpenAI cloud
- **kiconnect**  — a hosted OpenAI-compatible gateway (e.g. the university's
                   "KI-Connect"); set ``LLM_BASE_URL`` + ``OPENAI_API_KEY``
- **groq**       — OpenAI-compatible cloud

For all of those we issue a plain ``httpx`` POST so the helper has no hard
dependency on litellm/CrewAI. ``anthropic`` is the one non-OpenAI shape; it is
routed through the existing CrewAI ``LLM`` adapter.

Beyond the plain call, this module adds three production concerns:

1. **Bounded retries** — transient failures (timeouts, connection errors,
   HTTP 429/5xx) are retried up to ``_MAX_ATTEMPTS`` times with exponential
   backoff + jitter. Non-transient errors fail immediately.
2. **Structured outputs** — pass ``schema=SomePydanticModel`` and the request
   carries an OpenAI ``response_format: json_schema`` block (constrained
   decoding). Gateways that reject the parameter (HTTP 400/404/415/422) are
   detected and the call transparently falls back to a plain completion, so
   the existing "strip fences, then json.loads" parsing still applies.
3. **Telemetry** — every call records provider, model, latency, token usage
   and retry count into an in-process, thread-safe recorder. ``job-agent
   eval`` and the log output use it; nothing is sent anywhere.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from pydantic import BaseModel

from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

# Providers that speak the OpenAI Chat-Completions protocol.
_OPENAI_COMPATIBLE = {"ollama", "openai", "kiconnect", "groq"}

# Sensible default endpoints when LLM_BASE_URL is not set.
_DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    # kiconnect has no public default — it MUST be configured via LLM_BASE_URL.
}

# Transient HTTP statuses worth retrying (rate limit + server hiccups).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Statuses that usually mean "this gateway does not know response_format".
_SCHEMA_REJECTED_STATUS = {400, 404, 415, 422}
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_S = 0.5

# Injectable sleep so tests can run retries without waiting.
_sleep = time.sleep


@dataclass
class LLMCallRecord:
    """Telemetry for a single LLM call (successful or failed)."""

    provider: str
    model: str
    duration_s: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    structured: bool = False
    ok: bool = True
    error: str = ""


@dataclass
class _Telemetry:
    """Thread-safe in-process recorder — read by ``job-agent eval`` and logs."""

    _records: list[LLMCallRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, record: LLMCallRecord) -> None:
        with self._lock:
            self._records.append(record)

    def snapshot(self) -> list[LLMCallRecord]:
        with self._lock:
            return list(self._records)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def summary(self) -> dict[str, float]:
        """Aggregate view: calls, failures, retries, tokens, latency."""
        records = self.snapshot()
        calls = len(records)
        if not calls:
            return {"calls": 0.0}
        return {
            "calls": float(calls),
            "failed": float(sum(1 for r in records if not r.ok)),
            "retries": float(sum(r.retries for r in records)),
            "prompt_tokens": float(sum(r.prompt_tokens for r in records)),
            "completion_tokens": float(sum(r.completion_tokens for r in records)),
            "avg_latency_s": round(sum(r.duration_s for r in records) / calls, 3),
            "total_latency_s": round(sum(r.duration_s for r in records), 3),
        }


telemetry = _Telemetry()


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


def _response_format(schema: type[BaseModel], schema_name: str) -> dict[str, Any]:
    """Build an OpenAI ``response_format`` block from a Pydantic model."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": schema.model_json_schema(),
        },
    }


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter: 0.5s, 1s, 2s (+0..250ms)."""
    return _BACKOFF_BASE_S * (2.0**attempt) + random.uniform(0.0, 0.25)


def _extract_usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return 0, 0
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    return int(prompt or 0), int(completion or 0)


def _openai_compatible_chat(
    messages: list[dict[str, str]],
    schema: type[BaseModel] | None,
    schema_name: str,
) -> str:
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

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "stream": False,
    }
    use_schema = schema is not None
    if schema is not None:
        payload["response_format"] = _response_format(schema, schema_name)

    started = time.monotonic()
    retries = 0
    last_error: Exception | None = None

    for attempt in range(_MAX_ATTEMPTS):
        if attempt:
            retries += 1
        try:
            response = httpx.post(
                chat_completions_url(base),
                json=payload,
                headers=headers,
                timeout=settings.llm_call_timeout,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt + 1 < _MAX_ATTEMPTS:
                log.warning("[llm] transient network error (attempt %d): %s", attempt + 1, exc)
                _sleep(_backoff(attempt))
                continue
            break

        status = int(getattr(response, "status_code", 200))
        if use_schema and status in _SCHEMA_REJECTED_STATUS:
            # Gateway doesn't support response_format — drop it and retry now.
            log.info("[llm] gateway rejected json_schema (HTTP %d) — plain retry", status)
            payload.pop("response_format", None)
            use_schema = False
            continue
        if status in _RETRYABLE_STATUS:
            last_error = RuntimeError(f"HTTP {status} from LLM gateway")
            if attempt + 1 < _MAX_ATTEMPTS:
                log.warning("[llm] retryable HTTP %d (attempt %d)", status, attempt + 1)
                _sleep(_backoff(attempt))
                continue
            break

        response.raise_for_status()
        data: dict[str, Any] = response.json()
        prompt_tokens, completion_tokens = _extract_usage(data)
        duration = time.monotonic() - started
        telemetry.record(
            LLMCallRecord(
                provider=provider,
                model=settings.llm_model,
                duration_s=round(duration, 3),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                retries=retries,
                structured=use_schema,
            )
        )
        log.info(
            "[llm] %s/%s ok in %.2fs (tokens: %d prompt / %d completion, retries: %d)",
            provider,
            settings.llm_model,
            duration,
            prompt_tokens,
            completion_tokens,
            retries,
        )
        return str(data["choices"][0]["message"]["content"])

    duration = time.monotonic() - started
    telemetry.record(
        LLMCallRecord(
            provider=provider,
            model=settings.llm_model,
            duration_s=round(duration, 3),
            retries=retries,
            structured=use_schema,
            ok=False,
            error=str(last_error),
        )
    )
    raise RuntimeError(f"LLM call failed after {_MAX_ATTEMPTS} attempts: {last_error}")


def call_llm(
    messages: list[dict[str, str]],
    schema: type[BaseModel] | None = None,
    schema_name: str = "Result",
) -> str:
    """Call the configured LLM and return plain text.

    ``schema`` (a Pydantic model class) opts into OpenAI structured outputs:
    the request asks the gateway to constrain decoding to that JSON schema.
    Callers keep their tolerant JSON parsing as a second net — gateways
    without ``response_format`` support are detected and handled here.
    """
    if settings.llm_provider.lower() in _OPENAI_COMPATIBLE:
        return _openai_compatible_chat(messages, schema, schema_name)

    # anthropic (or anything else CrewAI/litellm can route) via the CrewAI adapter.
    from job_agent.agents.scout import _get_llm

    started = time.monotonic()
    try:
        raw = cast(Any, _get_llm()).call(messages=messages)
    except Exception as exc:
        telemetry.record(
            LLMCallRecord(
                provider=settings.llm_provider,
                model=settings.llm_model,
                duration_s=round(time.monotonic() - started, 3),
                ok=False,
                error=str(exc),
            )
        )
        raise
    telemetry.record(
        LLMCallRecord(
            provider=settings.llm_provider,
            model=settings.llm_model,
            duration_s=round(time.monotonic() - started, 3),
        )
    )
    if not isinstance(raw, str):
        return str(raw)
    return raw
