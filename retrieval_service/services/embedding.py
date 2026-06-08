"""Async-safe embedding service wrapper.

CPU-bound model inference is offloaded to a ThreadPoolExecutor so the
event loop never blocks.  A single model instance is kept warm for the
lifetime of the process.
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

import httpx
import numpy as np

logger = logging.getLogger(__name__)

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
_BEARER_KEY_RE = re.compile(r"(sk-or-|sk-)[A-Za-z0-9._-]+")


class EmbeddingProvider(Protocol):
    """Protocol for async embedding providers."""

    async def encode(self, text: str) -> list[float]: ...

    async def encode_batch(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingService:
    """Loads the embedding model once and exposes an async-safe interface."""

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-base-en-v1.5",
        device: str = "cpu",
        max_workers: int = 4,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._max_workers = max_workers
        self._model: object | None = None
        self._executor: ThreadPoolExecutor | None = None

    async def initialize(self) -> EmbeddingProvider:
        loop = asyncio.get_running_loop()
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        self._model = await loop.run_in_executor(
            self._executor, _load_model, self._model_name, self._device
        )
        logger.info(
            "embedding model loaded model=%s device=%s",
            self._model_name,
            self._device,
        )
        return self

    async def encode(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(
            self._executor, _encode_text, self._model, text
        )
        return vector

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(
            self._executor, _encode_texts, self._model, texts
        )
        return vectors

    async def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._model = None


class RemoteEmbeddingService:
    """Async OpenAI-compatible remote embedding provider."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str = OPENROUTER_EMBEDDINGS_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("embedding api key is required for remote providers")
        if not model_name or not model_name.strip():
            raise ValueError("embedding model_name is required")
        if not base_url or not base_url.strip():
            raise ValueError("embedding base_url is required")

        self._api_key = api_key
        self._model_name = model_name
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> EmbeddingProvider:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        logger.info(
            "remote embedding provider initialized model=%s url=%s",
            self._model_name,
            self._base_url,
        )
        return self

    async def encode(self, text: str) -> list[float]:
        vectors = await self.encode_batch([text])
        return vectors[0]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            await self.initialize()
        if not texts:
            return []

        response = await self._client.post(
            self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model_name,
                "input": texts,
            },
        )
        if not response.is_success:
            raise RemoteEmbeddingError(
                f"embedding provider returned {response.status_code}: "
                f"{_redact_key(response.text)}"
            )

        return _parse_embedding_response(response.json(), expected_count=len(texts))

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _load_model(model_name: str, device: str) -> object:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device=device)


def _encode_text(model: object, text: str) -> list[float]:
    vector = model.encode(text, normalize_embeddings=True)
    return _to_float_list(vector)


def _encode_texts(model: object, texts: list[str]) -> list[list[float]]:
    vectors = model.encode(texts, normalize_embeddings=True)
    return [_to_float_list(v) for v in vectors]


def _to_float_list(vector: np.ndarray) -> list[float]:
    return vector.astype(float).tolist()


class RemoteEmbeddingError(RuntimeError):
    """Raised when a remote embedding provider fails."""


def _parse_embedding_response(data: dict[str, Any], *, expected_count: int) -> list[list[float]]:
    items = data.get("data")
    if not isinstance(items, list):
        raise RemoteEmbeddingError("embedding response must contain a data list")
    if len(items) != expected_count:
        raise RemoteEmbeddingError(
            f"embedding response count mismatch: got {len(items)} expected {expected_count}"
        )

    vectors: list[list[float]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise RemoteEmbeddingError(f"embedding response item {index} must be an object")
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            raise RemoteEmbeddingError(
                f"embedding response item {index} must contain an embedding list"
            )
        vectors.append([float(value) for value in embedding])
    return vectors


def _redact_key(text: str) -> str:
    return _BEARER_KEY_RE.sub("[REDACTED]", text)
