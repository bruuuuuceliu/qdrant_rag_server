"""Compatibility shim for project RAG orchestration.

Canonical project RAG code lives in ``project_service.rag``.
"""

from project_service.rag import (
    GenerateResult,
    GenerationUnavailableError,
    IngestResult,
    RagEngine,
    SearchResult,
    _build_qdrant_filter,
    _make_response_cache_key,
    _make_search_cache_key,
)

__all__ = [
    "GenerateResult",
    "GenerationUnavailableError",
    "IngestResult",
    "RagEngine",
    "SearchResult",
    "_build_qdrant_filter",
    "_make_response_cache_key",
    "_make_search_cache_key",
]
