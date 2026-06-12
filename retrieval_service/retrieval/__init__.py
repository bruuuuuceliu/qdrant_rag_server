"""Reusable retrieval configuration, factories, and service facades."""

from retrieval_service.retrieval.service import (
    DeleteDocumentRequest,
    RawDocumentRequest,
    RetrievalSearchRequest,
    RetrievalSearchResult,
    RetrievalService,
)

__all__ = [
    "DeleteDocumentRequest",
    "RawDocumentRequest",
    "RetrievalSearchRequest",
    "RetrievalSearchResult",
    "RetrievalService",
]
