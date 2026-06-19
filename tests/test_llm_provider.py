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
