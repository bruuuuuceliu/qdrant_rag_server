"""Document handler protocol."""

from __future__ import annotations

from typing import Protocol

from ingestion_service.schemas import DocumentHandlingPolicy, HandlerOutput, SourceBlob


class DocumentHandler(Protocol):
    name: str
    supported_content_types: tuple[str, ...]
    supported_extensions: tuple[str, ...]
    resource_tier: str

    async def parse(
        self,
        source: SourceBlob,
        *,
        policy: DocumentHandlingPolicy,
    ) -> HandlerOutput:
        ...
