"""Compatibility shim for project RAG helper functions."""

from project_service.rag.helpers import (
    _elapsed_ms,
    _encode_batch,
    _encode_query,
    _safe_str_attr,
)

__all__ = ["_elapsed_ms", "_encode_batch", "_encode_query", "_safe_str_attr"]
