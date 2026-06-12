"""Standalone ingestion service orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ingestion_service.chunking import SectionAwareChunker
from ingestion_service.normalization import CleaningResult, DocumentCleaner
from ingestion_service.routing import FileRouter
from ingestion_service.schemas import (
    DocumentHandlingPolicy,
    IngestedChunk,
    IngestedDocument,
    RouteDecision,
    SourceBlob,
    SourceDescriptor,
)
from ingestion_service.source import load_source


@dataclass(frozen=True, slots=True)
class IngestionResult:
    document: IngestedDocument
    chunks: tuple[IngestedChunk, ...]
    raw_content: bytes
    source: SourceBlob
    route_decision: RouteDecision
    cleaning: CleaningResult

    @property
    def texts(self) -> list[str]:
        return [chunk.text for chunk in self.chunks]


class IngestionService:
    """Loads, routes, parses, and chunks one source."""

    def __init__(
        self,
        *,
        router: FileRouter | None = None,
        chunker: SectionAwareChunker | None = None,
        cleaner: DocumentCleaner | None = None,
    ) -> None:
        self._router = router or FileRouter()
        self._chunker = chunker or SectionAwareChunker()
        self._cleaner = cleaner or DocumentCleaner()

    async def process(
        self,
        source: SourceDescriptor | Any,
        *,
        policy: DocumentHandlingPolicy | None = None,
    ) -> IngestionResult:
        policy = policy or DocumentHandlingPolicy()
        descriptor = (
            source if isinstance(source, SourceDescriptor) else SourceDescriptor.from_request(source)
        )
        loaded = await load_source(descriptor, policy=policy)
        loaded = _ensure_document_id(loaded)
        routed = self._router.route(loaded, policy=policy)
        parsed = await routed.handler.parse(loaded, policy=policy)
        document = parsed.document
        cleaning = self._cleaner.clean(parsed.sections, policy=policy.cleaning)
        chunks = self._chunker.chunk(document, cleaning.sections)
        return IngestionResult(
            document=document,
            chunks=chunks,
            raw_content=loaded.content,
            source=loaded,
            route_decision=routed.decision,
            cleaning=cleaning,
        )


def _ensure_document_id(source: SourceBlob) -> SourceBlob:
    if source.document_id:
        return source
    return replace(source, document_id=source.checksum[:16])
