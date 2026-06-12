"""Legacy re-export shim — project RAG engine has moved to ``project_service.rag``.

Prefer importing from the new package:

    from project_service.rag import RagEngine, SearchResult
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
