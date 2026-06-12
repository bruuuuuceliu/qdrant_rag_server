"""Embedding utilities: error classes, response parsing, key redaction."""

from __future__ import annotations

import re
from typing import Any

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
_BEARER_KEY_RE = re.compile(r"(sk-or-|sk-)[A-Za-z0-9._-]+")


class RemoteEmbeddingError(RuntimeError):
    """Raised when a remote embedding provider fails."""


def _parse_embedding_response(
    data: dict[str, Any], *, expected_count: int
) -> list[list[float]]:
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
