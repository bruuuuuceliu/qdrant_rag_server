"""Reusable retrieval configuration, factories, and service facades."""

from retrieval_service.retrieval.app import RetrievalAppContext, create_app
from retrieval_service.retrieval.contracts import (
    RetrievalApiError,
    RetrievalDeleteDocumentCommand,
    RetrievalFilterSpec,
    RetrievalRawDocumentCommand,
    RetrievalResponseEnvelope,
    RetrievalSearchCommand,
    raw_document_result_to_mapping,
    search_result_to_mapping,
)
from retrieval_service.retrieval.handler import RetrievalApiHandler
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
    "RetrievalApiError",
    "RetrievalApiHandler",
    "RetrievalAppContext",
    "RetrievalDeleteDocumentCommand",
    "RetrievalFilterSpec",
    "RetrievalRawDocumentCommand",
    "RetrievalResponseEnvelope",
    "RetrievalSearchCommand",
    "RetrievalSearchRequest",
    "RetrievalSearchResult",
    "RetrievalService",
    "create_app",
    "raw_document_result_to_mapping",
    "search_result_to_mapping",
]
