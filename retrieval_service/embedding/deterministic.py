"""Deterministic embedding provider for local smoke and tests."""

from __future__ import annotations

import hashlib
import math
import re

from retrieval_service.embedding.protocols import EmbeddingProvider, EmbeddingTask


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class DeterministicHashEmbedding:
    """Small network-free embedding backend based on hashed token features."""

    def __init__(self, *, dimension: int = 384) -> None:
        if dimension < 1:
            raise ValueError("deterministic embedding dimension must be positive")
        self._dimension = int(dimension)

    async def initialize(self) -> EmbeddingProvider:
        return self

    async def encode(
        self,
        text: str,
        *,
        task: EmbeddingTask = "search",
    ) -> list[float]:
        return _embed_text(text, dimension=self._dimension)

    async def encode_batch(
        self,
        texts: list[str],
        *,
        task: EmbeddingTask = "ingest",
    ) -> list[list[float]]:
        return [_embed_text(text, dimension=self._dimension) for text in texts]

    async def shutdown(self) -> None:
        return None


def _embed_text(text: str, *, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
