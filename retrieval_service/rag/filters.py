"""Compatibility shim for project RAG filter translation."""

from project_service.rag.filters import _build_qdrant_filter

__all__ = ["_build_qdrant_filter"]
