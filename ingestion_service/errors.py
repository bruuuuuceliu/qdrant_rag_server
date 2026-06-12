"""Typed errors for standalone ingestion."""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for ingestion failures."""


class SourceLoadError(IngestionError):
    """Raised when source content cannot be loaded."""


class SourceTooLargeError(SourceLoadError):
    """Raised when source content exceeds policy limits."""


class UnsupportedContentTypeError(IngestionError):
    """Raised when no handler can process the source."""


class RouteError(IngestionError):
    """Raised when routing cannot produce an executable handler."""


class ParseError(IngestionError):
    """Raised when a handler fails to parse a supported source."""


class EmptyDocumentError(ParseError):
    """Raised when a source parses successfully but yields no usable text."""


class NeedsDoclingConversion(IngestionError):
    """Raised when the minimal worker should delegate conversion to Docling."""
