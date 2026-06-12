"""Small helper functions used by retrieval and ingest pipelines."""

from __future__ import annotations

import time
from typing import Any


def _elapsed_ms(start_ns: int) -> int:
    return int((time.monotonic_ns() - start_ns) / 1e6)


def _safe_str_attr(obj: Any, name: str) -> str:
    value = getattr(obj, name, "")
    return value if isinstance(value, str) else ""


async def _encode_query(embedding_provider: Any, text: str) -> list[float]:
    if hasattr(embedding_provider, "encode"):
        return await embedding_provider.encode(text, task="search")
    if callable(embedding_provider):
        return await embedding_provider(text)
    raise TypeError("embedding_provider must expose encode()")


async def _encode_batch(embedding_provider: Any, texts: list[str]) -> list[list[float]]:
    if hasattr(embedding_provider, "encode_batch"):
        return await embedding_provider.encode_batch(texts, task="ingest")
    raise TypeError("embedding_provider must expose encode_batch()")

