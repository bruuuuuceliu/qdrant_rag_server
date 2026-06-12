"""Compatibility shim for reusable cache-key builders."""

from retrieval_service.retrieval.cache_keys import (
    _make_response_cache_key,
    _make_search_cache_key,
)

__all__ = ["_make_response_cache_key", "_make_search_cache_key"]
