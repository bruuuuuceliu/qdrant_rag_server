"""Compatibility shim for project RAG result schemas."""

from project_service.schemas.results import (
    GenerateResult,
    GenerationUnavailableError,
    IngestResult,
    SearchResult,
)

__all__ = [
    "GenerateResult",
    "GenerationUnavailableError",
    "IngestResult",
    "SearchResult",
]
