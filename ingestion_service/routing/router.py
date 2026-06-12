"""Resource-aware file router."""

from __future__ import annotations

from dataclasses import dataclass

from ingestion_service.errors import NeedsDoclingConversion, UnsupportedContentTypeError
from ingestion_service.handlers import (
    CsvHandler,
    DoclingDocumentHandler,
    DocxNativeHandler,
    HtmlDocumentHandler,
    MarkdownDocumentHandler,
    MarkItDownHandler,
    PdfNativeTextHandler,
    PptxNativeHandler,
    TextDocumentHandler,
    XlsxHandler,
    ZipArchiveHandler,
)
from ingestion_service.handlers.base import DocumentHandler
from ingestion_service.schemas import DocumentHandlingPolicy, RouteDecision, SourceBlob
from ingestion_service.source import normalize_content_type, source_extension


@dataclass(frozen=True, slots=True)
class RoutedHandler:
    handler: DocumentHandler
    decision: RouteDecision


class FileRouter:
    """Selects a document handler by type, extension, policy, and resource tier."""

    def __init__(self, handlers: tuple[DocumentHandler, ...] | None = None) -> None:
        self._handlers = handlers or default_handlers()

    def route(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> RoutedHandler:
        content_type = normalize_content_type(source.content_type)
        extension = source_extension(source.source_uri, source.filename)
        self._validate_policy(content_type, extension, policy)
        candidates = [
            handler
            for handler in self._handlers
            if _resource_allowed(handler, policy)
            and _handler_matches(handler, content_type, extension)
        ]
        if candidates:
            selected = candidates[0]
            return RoutedHandler(
                handler=selected,
                decision=RouteDecision(
                    handler_name=str(getattr(selected, "name", selected.__class__.__name__)),
                    content_type=content_type,
                    extension=extension,
                    resource_tier=str(getattr(selected, "resource_tier", "minimal")),
                ),
            )
        if _docling_can_handle(content_type, extension) and policy.allow_docling:
            raise NeedsDoclingConversion(
                f"{content_type or extension} requires Docling conversion"
            )
        raise UnsupportedContentTypeError(
            f"no ingestion handler for content_type={content_type!r} extension={extension!r}"
        )

    def _validate_policy(
        self,
        content_type: str,
        extension: str,
        policy: DocumentHandlingPolicy,
    ) -> None:
        if policy.allowed_content_types and content_type not in {
            normalize_content_type(value) for value in policy.allowed_content_types
        }:
            raise UnsupportedContentTypeError(f"content type {content_type!r} is not allowed")
        allowed_extensions = policy.normalized_extensions()
        if allowed_extensions and extension and extension not in allowed_extensions:
            raise UnsupportedContentTypeError(f"extension {extension!r} is not allowed")


def default_handlers() -> tuple[DocumentHandler, ...]:
    return (
        TextDocumentHandler(),
        MarkdownDocumentHandler(),
        HtmlDocumentHandler(),
        CsvHandler(),
        PdfNativeTextHandler(),
        DocxNativeHandler(),
        PptxNativeHandler(),
        XlsxHandler(),
        ZipArchiveHandler(),
        MarkItDownHandler(),
        DoclingDocumentHandler(),
    )


def _resource_allowed(handler: DocumentHandler, policy: DocumentHandlingPolicy) -> bool:
    tier = str(getattr(handler, "resource_tier", "minimal"))
    if tier == "minimal":
        return True
    return tier == policy.resource_tier and policy.allow_docling


def _handler_matches(
    handler: DocumentHandler,
    content_type: str,
    extension: str,
) -> bool:
    content_types = {
        normalize_content_type(value)
        for value in getattr(handler, "supported_content_types", ())
    }
    extensions = {value.lower() for value in getattr(handler, "supported_extensions", ())}
    return content_type in content_types or extension in extensions


def _docling_can_handle(content_type: str, extension: str) -> bool:
    docling = DoclingDocumentHandler()
    return _handler_matches(docling, content_type, extension)
