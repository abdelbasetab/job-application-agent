"""LLM helper for the Profiler / Matcher / Writer text calls.

Most providers we support speak the OpenAI Chat-Completions protocol:

- **ollama**     — local, OpenAI-compatible endpoint at ``/v1/chat/completions``
- **openai**     — OpenAI cloud
- **kiconnect**  — a hosted OpenAI-compatible gateway (e.g. the university's
                   "KI-Connect"); set ``LLM_BASE_URL`` + ``OPENAI_API_KEY``
- **groq**       — OpenAI-compatible cloud

All providers use small, bounded ``httpx`` clients here, so the runtime does
not inherit an agent framework's transitive dependency and attack surface.

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

import json
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

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
    "anthropic": "https://api.anthropic.com/v1",
    # kiconnect has no public default — it MUST be configured via LLM_BASE_URL.
}

# Transient HTTP statuses worth retrying (rate limit + server hiccups).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Statuses that usually mean "this gateway does not know response_format".
_SCHEMA_REJECTED_STATUS = {400, 404, 415, 422}
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_S = 0.5
_MAX_PROMPT_CHARS = 200_000
_MAX_COMPLETION_CHARS = 1_000_000

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


def anthropic_messages_url(base_url: str) -> str:
    """Normalize an Anthropic base URL into the Messages API endpoint."""
    base = base_url.rstrip("/")
    if base.endswith("/messages"):
        return base
    if base.endswith("/v1") or "/v1/" in base:
        return f"{base}/messages"
    return f"{base}/v1/messages"


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
    try:
        prompt = max(0, min(1_000_000_000, int(usage.get("prompt_tokens", 0) or 0)))
        completion = max(
            0, min(1_000_000_000, int(usage.get("completion_tokens", 0) or 0))
        )
    except (TypeError, ValueError):
        return 0, 0
    return prompt, completion


def _validate_messages(messages: list[dict[str, str]]) -> None:
    if not messages or len(messages) > 100:
        raise ValueError("LLM request must contain between 1 and 100 messages.")
    total = 0
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise ValueError("LLM messages require a supported role and string content.")
        total += len(content)
        if total > _MAX_PROMPT_CHARS:
            raise ValueError(
                f"LLM prompt exceeds the {_MAX_PROMPT_CHARS:,}-character safety limit."
            )


def validate_llm_base_url(base_url: str, provider: str, api_key: str | None) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("LLM_BASE_URL must be a complete HTTP(S) URL.")
    if parsed.username or parsed.password:
        raise ValueError("LLM_BASE_URL must not contain embedded credentials.")
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    explicitly_private_ollama = (
        provider == "ollama"
        and not api_key
        and settings.allow_private_network_services
    )
    if parsed.scheme != "https" and not local and not explicitly_private_ollama:
        raise ValueError(
            "Remote LLM endpoints require HTTPS; plain HTTP is limited to localhost "
            "or an explicitly enabled private Ollama service."
        )


def _completion_content(data: object) -> str:
    if not isinstance(data, dict):
        raise ValueError("LLM gateway response is not a JSON object.")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("LLM gateway response has no completion choice.")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("LLM gateway response has no text content.")
    content = str(message["content"])
    if len(content) > _MAX_COMPLETION_CHARS:
        raise ValueError("LLM completion exceeds the response safety limit.")
    return content


def _anthropic_content(data: object) -> str:
    if not isinstance(data, dict):
        raise ValueError("Anthropic response is not a JSON object.")
    blocks = data.get("content")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("Anthropic response has no content blocks.")
    parts = [
        str(block["text"])
        for block in blocks
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]
    if not parts:
        raise ValueError("Anthropic response has no text content.")
    content = "".join(parts)
    if len(content) > _MAX_COMPLETION_CHARS:
        raise ValueError("LLM completion exceeds the response safety limit.")
    return content


def _extract_anthropic_usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return 0, 0
    try:
        prompt = max(0, min(1_000_000_000, int(usage.get("input_tokens", 0) or 0)))
        completion = max(0, min(1_000_000_000, int(usage.get("output_tokens", 0) or 0)))
    except (TypeError, ValueError):
        return 0, 0
    return prompt, completion


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
    validate_llm_base_url(base, provider, key)
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
    attempts_made = 0
    last_error: Exception | None = None

    for attempt in range(_MAX_ATTEMPTS):
        attempts_made = attempt + 1
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

        try:
            response.raise_for_status()
            raw_data: object = response.json()
            content = _completion_content(raw_data)
            data = raw_data if isinstance(raw_data, dict) else {}
        except Exception as exc:
            last_error = exc
            break
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
        return content

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
    raise RuntimeError(f"LLM call failed after {attempts_made} attempt(s): {last_error}")


def _anthropic_chat(
    messages: list[dict[str, str]],
    schema: type[BaseModel] | None,
    schema_name: str,
) -> str:
    """Call Anthropic's Messages API without a third-party routing layer."""
    provider = "anthropic"
    key = settings.anthropic_api_key
    if not key:
        raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY.")
    base = settings.llm_base_url or _DEFAULT_BASE_URLS[provider]
    validate_llm_base_url(base, provider, key)

    system_parts = [message["content"] for message in messages if message["role"] == "system"]
    api_messages = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]
    if not api_messages:
        raise ValueError("Anthropic requests require at least one user or assistant message.")
    if schema is not None:
        schema_instruction = (
            f"Return only JSON matching the {schema_name} schema: "
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(',', ':'))}"
        )
        if sum(len(part) for part in system_parts) + len(schema_instruction) > _MAX_PROMPT_CHARS:
            raise ValueError("Structured-output schema exceeds the prompt safety limit.")
        system_parts.append(schema_instruction)

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": api_messages,
        "max_tokens": 4096,
        "temperature": settings.llm_temperature,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }

    started = time.monotonic()
    retries = 0
    attempts_made = 0
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        attempts_made = attempt + 1
        if attempt:
            retries += 1
        try:
            response = httpx.post(
                anthropic_messages_url(base),
                json=payload,
                headers=headers,
                timeout=settings.llm_call_timeout,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt + 1 < _MAX_ATTEMPTS:
                log.warning("[llm] transient Anthropic error (attempt %d): %s", attempt + 1, exc)
                _sleep(_backoff(attempt))
                continue
            break

        status = int(getattr(response, "status_code", 200))
        if status in _RETRYABLE_STATUS:
            last_error = RuntimeError(f"HTTP {status} from Anthropic")
            if attempt + 1 < _MAX_ATTEMPTS:
                log.warning("[llm] retryable Anthropic HTTP %d (attempt %d)", status, attempt + 1)
                _sleep(_backoff(attempt))
                continue
            break
        try:
            response.raise_for_status()
            raw_data: object = response.json()
            content = _anthropic_content(raw_data)
            data = raw_data if isinstance(raw_data, dict) else {}
        except Exception as exc:
            last_error = exc
            break
        prompt_tokens, completion_tokens = _extract_anthropic_usage(data)
        duration = time.monotonic() - started
        telemetry.record(
            LLMCallRecord(
                provider=provider,
                model=settings.llm_model,
                duration_s=round(duration, 3),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                retries=retries,
                structured=schema is not None,
            )
        )
        return content

    duration = time.monotonic() - started
    telemetry.record(
        LLMCallRecord(
            provider=provider,
            model=settings.llm_model,
            duration_s=round(duration, 3),
            retries=retries,
            structured=schema is not None,
            ok=False,
            error=str(last_error),
        )
    )
    raise RuntimeError(f"LLM call failed after {attempts_made} attempt(s): {last_error}")


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
    _validate_messages(messages)
    provider = settings.llm_provider.lower()
    if provider in _OPENAI_COMPATIBLE:
        return _openai_compatible_chat(messages, schema, schema_name)
    if provider == "anthropic":
        return _anthropic_chat(messages, schema, schema_name)
    raise ValueError(
        f"Unsupported LLM_PROVIDER='{settings.llm_provider}'. Expected one of: "
        "ollama, openai, kiconnect, anthropic, groq."
    )
