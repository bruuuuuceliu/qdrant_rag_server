"""OpenAI-compatible remote embedding provider.

Works with OpenRouter, OpenAI, and any OpenAI-compatible embeddings API.
"""

from __future__ import annotations

import logging

import httpx

from retrieval_service.embedding.protocols import EmbeddingProvider, EmbeddingTask
from retrieval_service.embedding.utils import (
    OPENROUTER_EMBEDDINGS_URL,
    RemoteEmbeddingError,
    _parse_embedding_response,
    _redact_key,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleEmbedding:
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

    async def encode(
        self,
        text: str,
        *,
        task: EmbeddingTask = "search",
    ) -> list[float]:
        vectors = await self.encode_batch([text], task=task)
        return vectors[0]

    async def encode_batch(
        self,
        texts: list[str],
        *,
        task: EmbeddingTask = "ingest",
    ) -> list[list[float]]:
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
