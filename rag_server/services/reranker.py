"""Async-safe reranker service wrapper.

CPU-bound cross-encoder inference is offloaded to a ThreadPoolExecutor.
A single model instance is kept warm for the process lifetime.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class RerankFn(Protocol):
    """Protocol for async rerank callables.

    Receives ``(query, pairs)`` where each pair is ``(payload_dict, initial_score)``.
    Returns reranked ``list[tuple[dict, float]]`` sorted by relevance (highest first).
    """

    async def __call__(
        self,
        query: str,
        pairs: list[tuple[dict[str, Any], float]],
    ) -> list[tuple[dict[str, Any], float]]: ...


class RerankerService:
    """Loads a cross-encoder reranker once and exposes an async-safe interface."""

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-reranker-base",
        device: str = "cpu",
        max_workers: int = 4,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._max_workers = max_workers
        self._model: object | None = None
        self._executor: ThreadPoolExecutor | None = None

    async def initialize(self) -> RerankFn:
        loop = asyncio.get_running_loop()
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        self._model = await loop.run_in_executor(
            self._executor, _load_reranker, self._model_name, self._device
        )
        logger.info(
            "reranker model loaded model=%s device=%s",
            self._model_name,
            self._device,
        )
        return self.rerank

    async def rerank(
        self,
        query: str,
        pairs: list[tuple[dict[str, Any], float]],
    ) -> list[tuple[dict[str, Any], float]]:
        if not pairs:
            return []

        loop = asyncio.get_running_loop()
        texts = [pair[0].get("text", "") for pair in pairs]

        result = await loop.run_in_executor(
            self._executor, _rerank_texts, self._model, query, texts
        )
        return [
            (pairs[idx][0], float(score))
            for idx, score in result
        ]

    async def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._model = None


def _load_reranker(model_name: str, device: str) -> object:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, device=device)


def _rerank_texts(
    model: object,
    query: str,
    texts: list[str],
) -> list[tuple[int, float]]:
    pairs = [[query, text] for text in texts]
    scores = model.predict(pairs, show_progress_bar=False)
    ranked = sorted(
        enumerate(scores), key=lambda x: x[1], reverse=True
    )
    return [(int(idx), float(score)) for idx, score in ranked]
