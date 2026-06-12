"""Embedding providers package.

Provides pluggable embedding backends:
- ``LocalSentenceTransformerEmbedding`` -- local CPU/GPU inference
- ``OpenRouterEmbedding`` -- OpenRouter embeddings API
- ``OpenAICompatibleEmbedding`` -- remote OpenAI-compatible API (OpenRouter, OpenAI, etc.)

New providers implement the ``EmbeddingProvider`` protocol and register
with ``EmbeddingProviderFactory``.
"""

from __future__ import annotations

from retrieval_service.embedding.protocols import EmbeddingProvider, EmbeddingTask
from retrieval_service.embedding.factory import EmbeddingProviderFactory
from retrieval_service.embedding.local import LocalSentenceTransformerEmbedding
from retrieval_service.embedding.openai_compatible import OpenAICompatibleEmbedding
from retrieval_service.embedding.openrouter import OpenRouterEmbedding
from retrieval_service.embedding.utils import (
    RemoteEmbeddingError,
    _parse_embedding_response,
    _redact_key,
)

EmbeddingService = LocalSentenceTransformerEmbedding
RemoteEmbeddingService = OpenAICompatibleEmbedding

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
