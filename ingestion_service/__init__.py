"""Standalone document ingestion package."""

from ingestion_service.errors import (
    EmptyDocumentError,
    IngestionError,
    NeedsDoclingConversion,
    ParseError,
    RouteError,
    SourceLoadError,
    SourceTooLargeError,
    UnsupportedContentTypeError,
)
from ingestion_service.normalization import CleaningResult, DocumentCleaner, DroppedSection
from ingestion_service.routing import FileRouter
from ingestion_service.schemas import (
    CleaningPolicy,
    DocumentHandlingPolicy,
    IngestedChunk,
    IngestedDocument,
    IngestedSection,
    ResourceBudget,
    RouteDecision,
    SourceBlob,
    SourceDescriptor,
)
from ingestion_service.service import IngestionResult, IngestionService
from ingestion_service.server import IngestionAppContext

__all__ = [
    "DocumentHandlingPolicy",
    "CleaningPolicy",
    "CleaningResult",
    "DocumentCleaner",
    "DroppedSection",
    "EmptyDocumentError",
    "FileRouter",
    "IngestedChunk",
    "IngestedDocument",
    "IngestedSection",
    "IngestionError",
    "IngestionAppContext",
    "IngestionResult",
    "IngestionService",
    "NeedsDoclingConversion",
    "ParseError",
    "ResourceBudget",
    "RouteDecision",
    "RouteError",
    "SourceBlob",
    "SourceDescriptor",
    "SourceLoadError",
    "SourceTooLargeError",
    "UnsupportedContentTypeError",
]
