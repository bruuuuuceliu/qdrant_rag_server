"""Compatibility shim for the project RAG engine.

Canonical project RAG orchestration lives in ``project_service.rag.engine``.
Generic retrieval primitives live under ``retrieval_service.core`` and
``retrieval_service.services``.
"""

from project_service.rag.engine import (
    DEFAULT_CANDIDATE_COUNT,
    DEFAULT_TOP_K,
    GenerationUnavailableError,
    GenerateResult,
    IngestResult,
    RagEngine,
    SearchResult,
)

__all__ = [
    "DEFAULT_CANDIDATE_COUNT",
    "DEFAULT_TOP_K",
    "GenerateResult",
    "GenerationUnavailableError",
    "IngestResult",
    "RagEngine",
    "SearchResult",
]
