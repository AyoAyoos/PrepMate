"""Local-only embeddings through the user's existing Ollama service.

No hosted embedding provider is used. If Ollama is unavailable the callers
fall back to exact keyword search, so the assistant still works. Repeated
text is served from a small in-memory LRU cache to avoid paying Ollama's
timeout on every call.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import OrderedDict
from typing import Sequence

import httpx
from loguru import logger


class OllamaEmbedder:
    """Small async client for Ollama's ``/api/embed`` endpoint."""

    def __init__(self) -> None:
        self.base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        self.expected_dim = self._positive_int("EMBEDDING_DIM", 768)
        self.timeout = self._positive_float("OLLAMA_TIMEOUT_SECONDS", 10.0)
        self._client: httpx.AsyncClient | None = None
        self._cache_max = self._positive_int("EMBEDDING_CACHE_MAX_ENTRIES", 512)
        self._cache_ttl = self._positive_float("EMBEDDING_CACHE_TTL_SECONDS", 3600.0)
        self._cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    @staticmethod
    def _positive_int(name: str, default: int) -> int:
        try:
            value = int(os.getenv(name, str(default)))
            return value if value > 0 else default
        except ValueError:
            logger.error(f"Invalid {name}; using default {default}")
            return default

    @staticmethod
    def _positive_float(name: str, default: float) -> float:
        try:
            value = float(os.getenv(name, str(default)))
            return value if value > 0 else default
        except ValueError:
            logger.error(f"Invalid {name}; using default {default}")
            return default

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\0{text}".encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> list[float] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, vector = entry
        if expires_at < time.monotonic():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return vector

    def _cache_put(self, key: str, vector: list[float]) -> None:
        self._cache[key] = (time.monotonic() + self._cache_ttl, vector)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]] | None:
        cleaned = [text.strip() for text in texts if text and text.strip()]
        if not cleaned:
            return []

        results: list[list[float] | None] = [None] * len(cleaned)
        pending: list[int] = []
        for index, text in enumerate(cleaned):
            cached = self._cache_get(self._cache_key(text))
            if cached is not None:
                results[index] = cached
                self._cache_hits += 1
            else:
                pending.append(index)
                self._cache_misses += 1
        logger.info(
            f"Embedding cache: hits={self._cache_hits}, misses={self._cache_misses}, "
            f"size={len(self._cache)}/{self._cache_max}"
        )

        if pending:
            inputs = [cleaned[index] for index in pending]
            try:
                client = await self._get_client()
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": inputs},
                )
                response.raise_for_status()
                payload = response.json()
                vectors = payload.get("embeddings")
                if not isinstance(vectors, list) or len(vectors) != len(inputs):
                    raise ValueError(
                        f"Expected {len(inputs)} embeddings, got "
                        f"{len(vectors) if isinstance(vectors, list) else type(vectors).__name__}"
                    )

                validated: list[list[float]] = []
                for vector in vectors:
                    if not isinstance(vector, list) or len(vector) != self.expected_dim:
                        raise ValueError(
                            f"Expected {self.expected_dim}-dim embedding, got "
                            f"{len(vector) if isinstance(vector, list) else type(vector).__name__}"
                        )
                    validated.append([float(value) for value in vector])
            except Exception as exc:
                logger.error(
                    f"Ollama embedding failed ({self.model} @ {self.base_url}): {exc}"
                )
                return None

            for index, vector in zip(pending, validated):
                results[index] = vector
                self._cache_put(self._cache_key(cleaned[index]), vector)

        final = [vector for vector in results if vector is not None]
        if len(final) != len(cleaned):
            logger.error("Incomplete embedding result; falling back to keyword search")
            return None
        return final

    async def embed_text(self, text: str) -> list[float] | None:
        vectors = await self.embed_texts([text])
        return vectors[0] if vectors else None

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None


embedder = OllamaEmbedder()
