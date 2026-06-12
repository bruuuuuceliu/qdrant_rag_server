"""Compatibility source-loading helpers for ingest implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingestion_service import SourceDescriptor
from ingestion_service.source import load_source


@dataclass(frozen=True, slots=True)
class IngestSourceContent:
    source_uri: str
    text: str
    raw_content: bytes
    content_type: str


async def load_ingest_source(request: Any) -> IngestSourceContent:
    """Load source content through the standalone ingestion package."""

    source = await load_source(SourceDescriptor.from_request(request))
    text = source.text()
    return IngestSourceContent(
        source_uri=source.source_uri,
        text=text,
        raw_content=source.content,
        content_type=source.content_type,
    )
