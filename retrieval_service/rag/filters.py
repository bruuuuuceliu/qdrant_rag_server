"""Compatibility shim for reusable Qdrant filter rendering."""

from retrieval_service.query.qdrant_filters import _build_qdrant_filter

__all__ = ["_build_qdrant_filter"]
