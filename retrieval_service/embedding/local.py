"""Local sentence-transformer embedding provider.

CPU-bound model inference is offloaded to a ThreadPoolExecutor so the
event loop never blocks.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from retrieval_service.embedding.protocols import EmbeddingProvider, EmbeddingTask

logger = logging.getLogger(__name__)


class LocalSentenceTransformerEmbedding:
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

    async def encode(
        self,
        text: str,
        *,
        task: EmbeddingTask = "search",
    ) -> list[float]:
        if self._executor is None or self._model is None:
            await self.initialize()
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(
            self._executor, _encode_text, self._model, text
        )
        return vector

    async def encode_batch(
        self,
        texts: list[str],
        *,
        task: EmbeddingTask = "ingest",
    ) -> list[list[float]]:
        if not texts:
            return []
        if self._executor is None or self._model is None:
            await self.initialize()
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
