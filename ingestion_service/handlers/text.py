"""Plain text document handler."""

from __future__ import annotations

from ingestion_service.normalization import normalize_text
from ingestion_service.schemas import (
    DocumentHandlingPolicy,
    HandlerOutput,
    IngestedDocument,
    IngestedSection,
    SourceBlob,
)


class TextDocumentHandler:
    name = "text"
    supported_content_types = ("text/plain", "")
    supported_extensions = (".txt", "")
    resource_tier = "minimal"

    async def parse(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> HandlerOutput:
        del policy
        text = normalize_text(source.text())
        document = IngestedDocument(
            document_id=source.document_id,
            source_uri=source.source_uri,
            content_type=source.content_type or "text/plain",
            data_type=source.data_type,
            content_hash=source.checksum,
            handler_name=self.name,
            metadata={**source.metadata, "raw_text": text},
        )
        return HandlerOutput(
            document=document,
            sections=(
                IngestedSection(section_id="0", text=text or source.source_uri, order=0),
            ),
        )
