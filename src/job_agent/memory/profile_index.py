"""ChromaDB-backed profile memory for Sprint 3 semantic context."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path

import chromadb
import httpx
from chromadb.config import Settings as ChromaSettings

from job_agent.schemas import UserProfile
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9+#.]+")


class HashEmbeddingFunction:
    """Small deterministic embedding function that works fully offline.

    It is intentionally simple: tokens are hashed into a fixed-size vector.
    ChromaDB still handles persistence and nearest-neighbor querying, while
    the project avoids a network dependency for embeddings in demos/tests.
    """

    def __init__(self, dimensions: int = 128) -> None:
        self.dimensions = dimensions

    @staticmethod
    def name() -> str:
        return "job-agent-hash-embedding"

    @staticmethod
    def is_legacy() -> bool:
        return False

    @staticmethod
    def default_space() -> str:
        return "cosine"

    @staticmethod
    def supported_spaces() -> list[str]:
        return ["cosine"]

    def get_config(self) -> dict[str, int]:
        return {"dimensions": self.dimensions}

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vector[index] += sign
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]


class KIConnectEmbeddingFunction:
    """Embeddings via an OpenAI-compatible /embeddings endpoint (e.g. KI-Connect)."""

    def __init__(self, model: str, base_url: str, api_key: str | None) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""

    @staticmethod
    def name() -> str:
        return "job-agent-kiconnect-embedding"

    @staticmethod
    def is_legacy() -> bool:
        return False

    @staticmethod
    def default_space() -> str:
        return "cosine"

    @staticmethod
    def supported_spaces() -> list[str]:
        return ["cosine"]

    def get_config(self) -> dict[str, str]:
        return {"model": self.model, "base_url": self.base_url}

    def __call__(self, input: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            embeddings_url(self.base_url),
            json={"model": self.model, "input": list(input)},
            headers=headers,
            timeout=60.0,
        )
        response.raise_for_status()
        rows = response.json()["data"]
        return [list(row["embedding"]) for row in rows]

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)


def embeddings_url(base_url: str) -> str:
    """Normalize an OpenAI-compatible base URL into a full embeddings endpoint."""
    base = base_url.rstrip("/")
    if base.endswith("/embeddings"):
        return base
    if base.endswith("/v1") or "/v1/" in base or base.endswith("/openai/v1"):
        return f"{base}/embeddings"
    return f"{base}/v1/embeddings"


def _select_embedding_function() -> tuple[object, str]:
    """Use real gateway embeddings if configured + reachable, else offline hash."""
    model = settings.embedding_model
    provider = settings.llm_provider.lower()
    if (
        model
        and provider in {"openai", "kiconnect"}
        and settings.llm_base_url
        and settings.llm_api_key
    ):
        fn = KIConnectEmbeddingFunction(model, settings.llm_base_url, settings.llm_api_key)
        try:
            fn(["probe"])
            log.info("[profile-index] using gateway embeddings: %s", model)
            return fn, "kiconnect"
        except Exception as exc:
            log.warning("[profile-index] embedding probe failed (%s) — using hash", exc)
    return HashEmbeddingFunction(), "hash"


class ProfileVectorStore:
    """Persist and query profile snippets in ChromaDB."""

    def __init__(
        self,
        path: str | Path | None = None,
        collection_name: str = "candidate_profile",
    ) -> None:
        self.path = Path(path or settings.chroma_path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        embed_fn, tag = _select_embedding_function()
        self._collection = self._client.get_or_create_collection(
            name=f"{collection_name}_{tag}",
            embedding_function=embed_fn,  # type: ignore[arg-type]
        )
        log.info("[profile-index] opened chroma at %s (embeddings=%s)", self.path, tag)

    def upsert_profile(self, profile: UserProfile) -> None:
        docs, ids, metadata = self._profile_documents(profile)
        self._collection.upsert(documents=docs, ids=ids, metadatas=metadata)  # type: ignore[arg-type]
        log.info("[profile-index] upserted %d profile snippets", len(docs))

    def query(self, text: str, top_k: int = 3) -> list[str]:
        if top_k <= 0:
            return []
        result = self._collection.query(query_texts=[text], n_results=top_k)
        docs = result.get("documents") or [[]]
        return [doc for doc in docs[0] if isinstance(doc, str)]

    def _profile_documents(
        self, profile: UserProfile
    ) -> tuple[list[str], list[str], list[Mapping[str, str | int | float | bool | None]]]:
        docs: list[str] = []
        ids: list[str] = []
        metadata: list[Mapping[str, str | int | float | bool | None]] = []

        docs.append(
            f"{profile.name}: {profile.headline}. Skills: {', '.join(profile.skills)}. "
            f"Languages: {profile.languages}."
        )
        ids.append("profile-summary")
        metadata.append({"kind": "summary"})

        for index, exp in enumerate(profile.experience):
            docs.append(
                f"Experience: {exp.role} at {exp.company}. {exp.summary} "
                f"Skills used: {', '.join(exp.skills_used)}."
            )
            ids.append(f"experience-{index}")
            metadata.append({"kind": "experience", "company": exp.company})

        for index, edu in enumerate(profile.education):
            docs.append(
                f"Education: {edu.degree} in {edu.field} at {edu.institution} "
                f"from {edu.start} to {edu.end or 'present'}."
            )
            ids.append(f"education-{index}")
            metadata.append({"kind": "education", "institution": edu.institution})

        prefs = profile.preferences
        docs.append(
            "Preferences: locations "
            f"{', '.join(prefs.locations) or 'any'}, "
            f"remote_ok={prefs.remote_ok}, employment_types="
            f"{', '.join(prefs.employment_types) or 'any'}."
        )
        ids.append("preferences")
        metadata.append({"kind": "preferences"})

        return docs, ids, metadata
