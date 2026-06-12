"""Docling sidecar handler placeholder."""

from __future__ import annotations

from ingestion_service.errors import NeedsDoclingConversion
from ingestion_service.schemas import DocumentHandlingPolicy, HandlerOutput, SourceBlob


class DoclingDocumentHandler:
    name = "docling"
    supported_content_types = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/html",
        "image/png",
        "image/jpeg",
        "image/tiff",
    )
    supported_extensions = (
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".html",
        ".htm",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
    )
    resource_tier = "docling_sidecar"

    async def parse(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> HandlerOutput:
        del source
        if not policy.allow_docling:
            raise NeedsDoclingConversion("Docling conversion is disabled by policy")
        raise NeedsDoclingConversion(
            "Docling conversion should run in a sidecar for this deployment"
        )
