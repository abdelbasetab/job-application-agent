from __future__ import annotations

import pytest

from job_agent.memory import profile_index


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://chat.kiconnect.nrw/api/v1", "https://chat.kiconnect.nrw/api/v1/embeddings"),
        ("https://host/v1/", "https://host/v1/embeddings"),
        ("https://host/v1/embeddings", "https://host/v1/embeddings"),
        ("https://host", "https://host/v1/embeddings"),
    ],
)
def test_embeddings_url_normalizes_openai_compatible_base(base: str, expected: str) -> None:
    assert profile_index.embeddings_url(base) == expected


def test_kiconnect_embedding_function_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(profile_index.httpx, "post", fake_post)
    fn = profile_index.KIConnectEmbeddingFunction(
        model="Qwen 3 Embedding 8B",
        base_url="https://chat.kiconnect.nrw/api/v1",
        api_key="secret-key",
    )

    out = fn(["Profil: Python und RAG"])

    assert out == [[0.1, 0.2, 0.3]]
    assert captured["url"] == "https://chat.kiconnect.nrw/api/v1/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["model"] == "Qwen 3 Embedding 8B"
    assert captured["json"]["input"] == ["Profil: Python und RAG"]


def test_select_embedding_function_uses_kiconnect_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_call(self, input: list[str]) -> list[list[float]]:  # type: ignore[no-untyped-def]
        calls.append(input)
        return [[1.0, 0.0]]

    monkeypatch.setattr(profile_index.settings, "llm_provider", "kiconnect")
    monkeypatch.setattr(profile_index.settings, "embedding_model", "Qwen 3 Embedding 8B")
    monkeypatch.setattr(profile_index.settings, "llm_base_url", "https://chat.kiconnect.nrw/api/v1")
    monkeypatch.setattr(profile_index.settings, "openai_api_key", "secret-key")
    monkeypatch.setattr(profile_index.KIConnectEmbeddingFunction, "__call__", fake_call)

    fn, tag = profile_index._select_embedding_function()

    assert isinstance(fn, profile_index.KIConnectEmbeddingFunction)
    assert tag.startswith("gateway_")
    assert calls == [["probe"]]


def test_embedding_function_rejects_remote_plain_http() -> None:
    with pytest.raises(ValueError, match="require HTTPS"):
        profile_index.KIConnectEmbeddingFunction(
            model="embedding-model",
            base_url="http://gateway.example/v1",
            api_key="secret-key",
        )


def test_embedding_function_rejects_invalid_vector_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"data": [{"embedding": [0.1, float("nan")]}]}

    monkeypatch.setattr(
        profile_index.httpx,
        "post",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    fn = profile_index.KIConnectEmbeddingFunction(
        model="embedding-model",
        base_url="https://gateway.example/v1",
        api_key="secret-key",
    )

    with pytest.raises(ValueError, match="non-finite"):
        fn(["profile"])
