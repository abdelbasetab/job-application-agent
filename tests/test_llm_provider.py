"""Offline tests for the OpenAI-compatible LLM client (incl. KI-Connect)."""

from __future__ import annotations

import pytest

from job_agent.utils import llm


@pytest.mark.parametrize(
    "base,expected",
    [
        ("http://localhost:11434", "http://localhost:11434/v1/chat/completions"),
        ("https://host/v1", "https://host/v1/chat/completions"),
        ("https://host/v1/", "https://host/v1/chat/completions"),
        ("https://host/v1/chat/completions", "https://host/v1/chat/completions"),
        ("https://api.groq.com/openai/v1", "https://api.groq.com/openai/v1/chat/completions"),
    ],
)
def test_chat_completions_url(base, expected):
    assert llm.chat_completions_url(base) == expected


def test_call_llm_kiconnect_builds_request(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "hello"}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(llm.settings, "llm_provider", "kiconnect")
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://kic.example/v1")
    monkeypatch.setattr(llm.settings, "openai_api_key", "secret-key")
    monkeypatch.setattr(llm.settings, "llm_model", "gpt-4o-mini")
    monkeypatch.setattr(llm.httpx, "post", fake_post)

    out = llm.call_llm([{"role": "user", "content": "hi"}])

    assert out == "hello"
    assert captured["url"] == "https://kic.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["model"] == "gpt-4o-mini"
    assert captured["json"]["messages"][0]["content"] == "hi"


def test_call_llm_requires_base_url_for_kiconnect(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "kiconnect")
    monkeypatch.setattr(llm.settings, "llm_base_url", None)
    with pytest.raises(RuntimeError):
        llm.call_llm([{"role": "user", "content": "hi"}])


def test_call_llm_anthropic_uses_direct_messages_api(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "content": [{"type": "text", "text": "hello"}],
                "usage": {"input_tokens": 6, "output_tokens": 2},
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(llm.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(llm.settings, "llm_base_url", None)
    monkeypatch.setattr(llm.settings, "anthropic_api_key", "anthropic-secret")
    monkeypatch.setattr(llm.settings, "llm_model", "claude-test")
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.telemetry.reset()

    out = llm.call_llm(
        [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hi"},
        ]
    )

    assert out == "hello"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "anthropic-secret"
    assert captured["json"]["system"] == "Be concise."
    assert captured["json"]["messages"] == [{"role": "user", "content": "Hi"}]
    [record] = llm.telemetry.snapshot()
    assert record.prompt_tokens == 6
    assert record.completion_tokens == 2


def test_call_llm_anthropic_requires_key(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(llm.settings, "anthropic_api_key", None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.call_llm([{"role": "user", "content": "hi"}])


def test_call_llm_rejects_remote_plain_http_with_api_key(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "kiconnect")
    monkeypatch.setattr(llm.settings, "llm_base_url", "http://gateway.example/v1")
    monkeypatch.setattr(llm.settings, "openai_api_key", "secret-key")

    with pytest.raises(ValueError, match="require HTTPS"):
        llm.call_llm([{"role": "user", "content": "hi"}])


class _Resp:
    """Minimal fake httpx response with a controllable status code."""

    def __init__(self, status_code: int = 200, content: str = "ok", usage: dict | None = None):
        self.status_code = status_code
        self._content = content
        self._usage = usage or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": self._content}}],
            "usage": self._usage,
        }


@pytest.fixture
def ollama_env(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "ollama")
    monkeypatch.setattr(llm.settings, "llm_base_url", "http://localhost:11434")
    monkeypatch.setattr(llm.settings, "llm_model", "test-model")
    monkeypatch.setattr(llm, "_sleep", lambda _s: None)  # retries must not wait in tests
    llm.telemetry.reset()


def test_call_llm_retries_transient_errors_then_succeeds(monkeypatch, ollama_env):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return _Resp(429)
        return _Resp(200, "done", usage={"prompt_tokens": 7, "completion_tokens": 3})

    monkeypatch.setattr(llm.httpx, "post", fake_post)

    assert llm.call_llm([{"role": "user", "content": "hi"}]) == "done"
    assert calls["n"] == 3

    [record] = llm.telemetry.snapshot()
    assert record.ok
    assert record.retries == 2
    assert record.prompt_tokens == 7
    assert record.completion_tokens == 3


def test_call_llm_gives_up_after_max_attempts(monkeypatch, ollama_env):
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: _Resp(503))

    with pytest.raises(RuntimeError, match="failed after"):
        llm.call_llm([{"role": "user", "content": "hi"}])

    [record] = llm.telemetry.snapshot()
    assert not record.ok
    assert "503" in record.error


def test_structured_output_sends_json_schema(monkeypatch, ollama_env):
    from pydantic import BaseModel

    class Out(BaseModel):
        x: int = 0

    payloads: list[dict] = []

    def fake_post(url, **kwargs):
        payloads.append(kwargs["json"])
        return _Resp(200, '{"x": 1}')

    monkeypatch.setattr(llm.httpx, "post", fake_post)

    out = llm.call_llm([{"role": "user", "content": "hi"}], schema=Out, schema_name="Out")

    assert out == '{"x": 1}'
    response_format = payloads[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "Out"
    assert response_format["json_schema"]["schema"]["properties"]["x"]["type"] == "integer"


def test_structured_output_falls_back_when_gateway_rejects_schema(monkeypatch, ollama_env):
    from pydantic import BaseModel

    class Out(BaseModel):
        x: int = 0

    payloads: list[dict] = []

    def fake_post(url, **kwargs):
        payloads.append(dict(kwargs["json"]))  # copy — the client mutates its payload
        if "response_format" in kwargs["json"]:
            return _Resp(400)  # gateway without structured-output support
        return _Resp(200, '{"x": 2}')

    monkeypatch.setattr(llm.httpx, "post", fake_post)

    out = llm.call_llm([{"role": "user", "content": "hi"}], schema=Out)

    assert out == '{"x": 2}'
    assert "response_format" in payloads[0]
    assert "response_format" not in payloads[1]


def test_telemetry_summary_aggregates(monkeypatch, ollama_env):
    monkeypatch.setattr(
        llm.httpx,
        "post",
        lambda url, **kw: _Resp(200, "ok", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    )

    llm.call_llm([{"role": "user", "content": "a"}])
    llm.call_llm([{"role": "user", "content": "b"}])

    summary = llm.telemetry.summary()
    assert summary["calls"] == 2
    assert summary["failed"] == 0
    assert summary["prompt_tokens"] == 20
    assert summary["completion_tokens"] == 10


def test_call_llm_rejects_oversized_prompt_before_network(monkeypatch, ollama_env):
    def forbidden_post(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("network must not be called")

    monkeypatch.setattr(llm.httpx, "post", forbidden_post)
    with pytest.raises(ValueError, match="safety limit"):
        llm.call_llm([{"role": "user", "content": "x" * (llm._MAX_PROMPT_CHARS + 1)}])


def test_invalid_gateway_shape_is_recorded_as_failure(monkeypatch, ollama_env):
    class InvalidResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"choices": []}

    monkeypatch.setattr(llm.httpx, "post", lambda *_args, **_kwargs: InvalidResponse())

    with pytest.raises(RuntimeError, match="failed after"):
        llm.call_llm([{"role": "user", "content": "hi"}])

    [record] = llm.telemetry.snapshot()
    assert record.ok is False
    assert "completion choice" in record.error
