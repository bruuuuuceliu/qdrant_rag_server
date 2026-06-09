"""Sparse text encoder interfaces and FastEmbed adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SparseVector:
    indices: list[int]
    values: list[float]


class SparseTextEncoder(Protocol):
    async def encode(self, text: str) -> SparseVector:
        ...

    async def encode_batch(self, texts: list[str]) -> list[SparseVector]:
        ...


class FastEmbedSparseTextEncoder:
    """Sparse BM25 text encoder backed by FastEmbed.

    FastEmbed is imported lazily so dense-only deployments and unit tests do not
    need the optional dependency at import time.
    """

    def __init__(self, model_name: str = "Qdrant/bm25") -> None:
        self._model_name = model_name
        self._model: Any | None = None

    async def encode(self, text: str) -> SparseVector:
        vectors = await self.encode_batch([text])
        return vectors[0]

    async def encode_batch(self, texts: list[str]) -> list[SparseVector]:
        if not texts:
            return []
        return await asyncio.to_thread(self._encode_batch_sync, texts)

    def _encode_batch_sync(self, texts: list[str]) -> list[SparseVector]:
        model = self._load_model()
        encoded = list(model.embed(texts))
        return [_to_sparse_vector(vector) for vector in encoded]

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from fastembed import SparseTextEmbedding
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "fastembed is required for Qdrant sparse BM25 retrieval. "
                "Install the sparse retrieval extra before using bm25 or hybrid mode."
            ) from exc
        self._model = SparseTextEmbedding(model_name=self._model_name)
        return self._model


def _to_sparse_vector(vector: Any) -> SparseVector:
    indices = getattr(vector, "indices", None)
    values = getattr(vector, "values", None)
    if indices is None or values is None:
        raise ValueError("sparse encoder returned an object without indices/values")
    return SparseVector(
        indices=[int(index) for index in indices],
        values=[float(value) for value in values],
    )
