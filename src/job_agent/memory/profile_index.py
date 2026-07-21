"""Small local vector index for persisted profile context.

The index deliberately uses SQLite instead of embedding a vector-database
server.  A candidate profile contains only a handful of snippets, so an exact
cosine scan is faster than the operational and security cost of a separate
ANN dependency while keeping the same persistent RAG behaviour.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import httpx

from job_agent.schemas import UserProfile
from job_agent.utils.config import settings
from job_agent.utils.llm import validate_llm_base_url
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9+#.]+")


class EmbeddingFunction(Protocol):
    """Minimal interface shared by local and gateway embeddings."""

    def __call__(self, input: list[str]) -> list[list[float]]: ...


class HashEmbeddingFunction:
    """Small deterministic embedding function that works fully offline.

    It is intentionally simple: tokens are hashed into a fixed-size vector.
    SQLite handles persistence and the tiny profile corpus is searched with an
    exact cosine scan, avoiding a network dependency in demos/tests.
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
        validate_llm_base_url(base_url, "kiconnect", api_key)
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
        if not input or len(input) > 128:
            raise ValueError("Embedding request must contain between 1 and 128 texts.")
        if any(not isinstance(text, str) or len(text) > 20_000 for text in input):
            raise ValueError("Embedding input is invalid or too large.")
        if sum(len(text) for text in input) > 200_000:
            raise ValueError("Embedding request exceeds the total text limit.")
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
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) != len(input):
            raise ValueError("Embedding gateway returned the wrong number of vectors.")
        parsed: list[tuple[int, list[float]]] = []
        dimensions: int | None = None
        for position, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
                raise ValueError("Embedding gateway returned an invalid vector.")
            raw_vector = row["embedding"]
            if not raw_vector or len(raw_vector) > 16_384:
                raise ValueError("Embedding vector has an invalid dimension.")
            vector: list[float] = []
            for value in raw_vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("Embedding vector contains a non-numeric value.")
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("Embedding vector contains a non-finite value.")
                vector.append(number)
            dimensions = dimensions or len(vector)
            if len(vector) != dimensions:
                raise ValueError("Embedding vectors have inconsistent dimensions.")
            raw_index = row.get("index", position)
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise ValueError("Embedding vector index is invalid.")
            parsed.append((raw_index, vector))
        parsed.sort(key=lambda item: item[0])
        if [index for index, _vector in parsed] != list(range(len(input))):
            raise ValueError("Embedding vector indexes are incomplete.")
        return [vector for _index, vector in parsed]

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


def _select_embedding_function() -> tuple[EmbeddingFunction, str]:
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
            config = f"{settings.llm_base_url}|{model}"
            fingerprint = hashlib.sha256(config.encode("utf-8")).hexdigest()[:12]
            return fn, f"gateway_{fingerprint}"
        except Exception as exc:
            log.warning("[profile-index] embedding probe failed (%s) — using hash", exc)
    return HashEmbeddingFunction(), "hash_128"


class ProfileVectorStore:
    """Persist and query a small, per-user profile corpus in SQLite."""

    def __init__(
        self,
        path: str | Path | None = None,
        collection_name: str = "candidate_profile",
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", collection_name):
            raise ValueError("Profile-index collection name is invalid.")
        self.path = Path(path or settings.profile_index_path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._db_path = self.path / "profile_vectors.sqlite3"
        self._embedding_function, tag = _select_embedding_function()
        self._collection_name = f"{collection_name}_{tag}"
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_vectors (
                    collection_name TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    document TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    PRIMARY KEY (collection_name, document_id)
                )
                """
            )
        log.info("[profile-index] opened SQLite index at %s (embeddings=%s)", self.path, tag)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def upsert_profile(self, profile: UserProfile) -> None:
        docs, ids, metadata = self._profile_documents(profile)
        vectors = self._embedding_function(docs)
        _validate_embedding_rows(vectors, expected=len(docs))
        rows = [
            (
                self._collection_name,
                document_id,
                document,
                json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
                json.dumps(vector, separators=(",", ":")),
            )
            for document_id, document, meta, vector in zip(
                ids, docs, metadata, vectors, strict=True
            )
        ]
        with self._connect() as conn:
            existing = {
                str(row[0])
                for row in conn.execute(
                    "SELECT document_id FROM profile_vectors WHERE collection_name = ?",
                    (self._collection_name,),
                )
            }
            stale = sorted(existing.difference(ids))
            if stale:
                conn.executemany(
                    "DELETE FROM profile_vectors "
                    "WHERE collection_name = ? AND document_id = ?",
                    [(self._collection_name, document_id) for document_id in stale],
                )
            conn.executemany(
                """
                INSERT INTO profile_vectors (
                    collection_name, document_id, document, metadata_json, embedding_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(collection_name, document_id) DO UPDATE SET
                    document = excluded.document,
                    metadata_json = excluded.metadata_json,
                    embedding_json = excluded.embedding_json
                """,
                rows,
            )
        log.info(
            "[profile-index] upserted %d profile snippets (removed %d stale)",
            len(docs),
            len(stale),
        )

    def query(self, text: str, top_k: int = 3) -> list[str]:
        query_text = text.strip()
        if top_k <= 0 or not query_text:
            return []
        if len(query_text) > 20_000:
            raise ValueError("Profile-index query exceeds the text limit.")
        [query_vector] = self._embedding_function([query_text])
        _validate_embedding_rows([query_vector], expected=1)
        with self._connect() as conn:
            rows = list(
                conn.execute(
                    "SELECT document_id, document, embedding_json "
                    "FROM profile_vectors WHERE collection_name = ?",
                    (self._collection_name,),
                )
            )
        scored: list[tuple[float, str, str]] = []
        for raw_document_id, raw_document, raw_embedding in rows:
            try:
                parsed = json.loads(str(raw_embedding))
                if not isinstance(parsed, list):
                    continue
                vector = [float(value) for value in parsed]
                _validate_embedding_rows([vector], expected=1)
            except (TypeError, ValueError, json.JSONDecodeError):
                log.warning(
                    "[profile-index] ignored corrupt vector for document %s",
                    raw_document_id,
                )
                continue
            similarity = _cosine_similarity(query_vector, vector)
            scored.append((similarity, str(raw_document_id), str(raw_document)))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [document for _score, _document_id, document in scored[: min(top_k, 50)]]

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
        docs[-1] = docs[-1][:12_000]
        ids.append("profile-summary")
        metadata.append({"kind": "summary"})

        for index, exp in enumerate(profile.experience):
            docs.append(
                f"Experience: {exp.role} at {exp.company}. {exp.summary} "
                f"Skills used: {', '.join(exp.skills_used)}."
            )
            docs[-1] = docs[-1][:12_000]
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


def _validate_embedding_rows(vectors: list[list[float]], *, expected: int) -> None:
    if len(vectors) != expected:
        raise ValueError("Embedding function returned the wrong number of vectors.")
    dimensions: int | None = None
    for vector in vectors:
        if not vector or len(vector) > 16_384:
            raise ValueError("Embedding vector has an invalid dimension.")
        dimensions = dimensions or len(vector)
        if len(vector) != dimensions:
            raise ValueError("Embedding vectors have inconsistent dimensions.")
        if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in vector):
            raise ValueError("Embedding vector contains an invalid numeric value.")


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
