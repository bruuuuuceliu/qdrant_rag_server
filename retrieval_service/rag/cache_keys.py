"""Compatibility shim for project RAG cache-key builders."""

from project_service.rag.cache_keys import _make_response_cache_key, _make_search_cache_key

__all__ = ["_make_response_cache_key", "_make_search_cache_key"]
