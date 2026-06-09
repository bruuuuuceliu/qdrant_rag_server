"""RAG package — retrieval-augmented generation orchestration."""

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


def __getattr__(name: str):
    if name == "RagEngine":
        from project_service.rag.engine import RagEngine

        return RagEngine
    if name in {
        "GenerateResult",
        "GenerationUnavailableError",
        "IngestResult",
        "SearchResult",
    }:
        from project_service import schemas

        return getattr(schemas, name)
    if name == "_build_qdrant_filter":
        from project_service.rag.filters import _build_qdrant_filter

        return _build_qdrant_filter
    if name == "_make_response_cache_key":
        from project_service.rag.cache_keys import _make_response_cache_key

        return _make_response_cache_key
    if name == "_make_search_cache_key":
        from project_service.rag.cache_keys import _make_search_cache_key

        return _make_search_cache_key
    raise AttributeError(name)
