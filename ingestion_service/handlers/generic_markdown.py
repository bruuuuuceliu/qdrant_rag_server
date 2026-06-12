"""Narrow MarkItDown fallback handler."""

from __future__ import annotations

from ingestion_service.errors import ParseError
from ingestion_service.handlers.text import TextDocumentHandler
from ingestion_service.schemas import DocumentHandlingPolicy, HandlerOutput, SourceBlob


class MarkItDownHandler:
    name = "markitdown"
    supported_content_types = ("application/octet-stream",)
    supported_extensions = ()
    resource_tier = "minimal"

    async def parse(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> HandlerOutput:
        try:
            from markitdown import MarkItDown  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            return await TextDocumentHandler().parse(source, policy=policy)
        try:
            result = MarkItDown().convert(source.source_uri)
        except Exception as exc:
            raise ParseError(f"MarkItDown conversion failed: {exc}") from exc
        updated = SourceBlob(
            source_uri=source.source_uri,
            content=str(result.text_content).encode("utf-8"),
            content_type="text/markdown",
            filename=source.filename,
            document_id=source.document_id,
            data_type=source.data_type,
            checksum=source.checksum,
            metadata=dict(source.metadata),
        )
        return await TextDocumentHandler().parse(updated, policy=policy)
