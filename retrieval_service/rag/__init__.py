"""RAG package — core retrieval-augmented generation orchestration.

The engine bridges validated gateway requests to backend services
(embedding, vector store, reranker, cache, LLM generation).
"""

from retrieval_service.rag.cache_keys import (
    _make_response_cache_key,
    _make_search_cache_key,
)
from retrieval_service.rag.engine import RagEngine
from retrieval_service.rag.filters import _build_qdrant_filter
from retrieval_service.rag.schemas import (
    GenerationUnavailableError,
    GenerateResult,
    IngestResult,
    SearchResult,
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
