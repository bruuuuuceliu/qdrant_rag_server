"""Embedding provider protocol and shared types."""

from __future__ import annotations

from typing import Literal, Protocol

EmbeddingTask = Literal["ingest", "search", "update"]


class EmbeddingProvider(Protocol):
    """Protocol for async embedding providers."""

    async def initialize(self) -> "EmbeddingProvider":
        """Open provider resources and return self."""
        ...

    async def encode(
        self,
        text: str,
        *,
        task: EmbeddingTask = "search",
    ) -> list[float]:
        """Embed one text string."""
        ...

    async def encode_batch(
        self,
        texts: list[str],
        *,
        task: EmbeddingTask = "ingest",
    ) -> list[list[float]]:
        """Embed many text strings, preserving input order."""
        ...

    async def shutdown(self) -> None:
        """Close provider resources."""
        ...
