"""Async-safe embedding service wrapper.

Legacy re-export shim — all implementations have moved to
``retrieval_service.embedding``.  Prefer importing from the new package:

    from retrieval_service.embedding import EmbeddingProviderFactory
    from retrieval_service.embedding import LocalSentenceTransformerEmbedding
    from retrieval_service.embedding import OpenRouterEmbedding
    from retrieval_service.embedding import OpenAICompatibleEmbedding

This module remains for backward compatibility.
"""

from __future__ import annotations

from retrieval_service.embedding import EmbeddingProviderFactory
from retrieval_service.embedding import EmbeddingProvider
from retrieval_service.embedding import EmbeddingService
from retrieval_service.embedding import EmbeddingTask
from retrieval_service.embedding import LocalSentenceTransformerEmbedding
from retrieval_service.embedding import OpenAICompatibleEmbedding
from retrieval_service.embedding import OpenRouterEmbedding
from retrieval_service.embedding import RemoteEmbeddingError
from retrieval_service.embedding import RemoteEmbeddingService
from retrieval_service.embedding import _parse_embedding_response
from retrieval_service.embedding import _redact_key

__all__ = [
    "EmbeddingProvider",
    "EmbeddingProviderFactory",
    "EmbeddingService",
    "EmbeddingTask",
    "LocalSentenceTransformerEmbedding",
    "OpenAICompatibleEmbedding",
    "OpenRouterEmbedding",
    "RemoteEmbeddingError",
    "RemoteEmbeddingService",
    "_parse_embedding_response",
    "_redact_key",
]
