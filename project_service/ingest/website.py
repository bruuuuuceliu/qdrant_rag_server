"""Website source ingester."""

from __future__ import annotations

from typing import Any

from project_service.adapters.website import WebsiteChunkPayload, WebsiteDocument
from project_service.ingest.source import ProjectSourceIngester
from project_service.schemas import ProjectChunk
from retrieval_service.ingest.source import IngestSourceContent


class WebsiteIngester(ProjectSourceIngester):
    """Prepare website URLs or local HTML/text files for indexing."""

    async def build_document(
        self,
        request: Any,
        source: IngestSourceContent,
        *,
        config: Any | None = None,
    ) -> WebsiteDocument:
        base = await super().build_document(request, source, config=config)
        return WebsiteDocument(
            project_id=base.project_id,
            user_id=base.user_id,
            kb_id=base.kb_id,
            doc_id=base.doc_id,
            source_uri=base.source_uri,
            content_type=base.content_type,
            data_type=base.data_type,
            visibility=base.visibility,
            content_hash=base.content_hash,
            embedding_version=base.embedding_version,
            chunker_version=base.chunker_version,
            metadata=base.metadata,
            url=source.source_uri,
            canonical_url=source.source_uri,
            page_title=source.source_uri,
            page_description="",
        )

    async def build_payload(
        self,
        chunk: ProjectChunk,
        source: IngestSourceContent,
        *,
        config: Any | None = None,
    ) -> WebsiteChunkPayload:
        del source, config
        url = chunk.metadata.get("url", "")
        section = chunk.metadata.get("section", "")
        title = chunk.metadata.get("page_title", "")
        return WebsiteChunkPayload(
            payload_id=chunk.chunk_id,
            project_id=chunk.project_id,
            user_id=chunk.user_id,
            kb_id=chunk.kb_id,
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            data_type=chunk.data_type,
            visibility=chunk.visibility,
            content_hash=chunk.content_hash,
            embedding_version=chunk.embedding_version,
            chunker_version=chunk.chunker_version,
            metadata=dict(chunk.metadata),
            url=url,
            canonical_url=url,
            page_title=title,
            section_heading=section,
        )
