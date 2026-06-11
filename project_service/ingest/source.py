"""Project-RAG source ingester primitives."""

from __future__ import annotations

import hashlib
from typing import Any

from project_service.schemas import (
    ProjectChunk,
    ProjectChunkPayload,
    ProjectDocument,
)
from retrieval_service.ingest.ingester import PreparedIngestData
from retrieval_service.ingest.source import IngestSourceContent, load_ingest_source


class ProjectSourceIngester:
    """Prepare a source URI or local file for project-scoped indexing."""

    async def prepare(
        self,
        request: Any,
        *,
        config: Any | None = None,
    ) -> PreparedIngestData:
        source = await load_ingest_source(request)
        document = await self.build_document(request, source, config=config)
        chunks = tuple(await self.build_chunks(document, source, config=config))
        payloads = tuple(
            [
                await self.build_payload(chunk, source, config=config)
                for chunk in chunks
            ]
        )
        return PreparedIngestData(
            document=document,
            chunks=chunks,
            payloads=payloads,
            raw_content=source.raw_content,
        )

    async def build_document(
        self,
        request: Any,
        source: IngestSourceContent,
        *,
        config: Any | None = None,
    ) -> ProjectDocument:
        del config
        metadata = dict(getattr(request, "metadata", {}) or {})
        metadata.setdefault("raw_text", source.text)
        return ProjectDocument(
            project_id=request.project_id,
            user_id=request.user_id,
            kb_id=request.kb_id,
            doc_id=request.doc_id,
            source_uri=source.source_uri,
            content_type=source.content_type,
            data_type=str(metadata.get("data_type", "document")),
            visibility=str(metadata.get("visibility", "private")),
            content_hash=str(
                metadata.get("content_hash") or _content_hash(source.raw_content)
            ),
            embedding_version=str(metadata.get("embedding_version", "")),
            chunker_version=str(metadata.get("chunker_version", "v1")),
            metadata=metadata,
        )

    async def build_chunks(
        self,
        document: ProjectDocument,
        source: IngestSourceContent,
        *,
        config: Any | None = None,
    ) -> list[ProjectChunk]:
        del config
        text = source.text or document.source_uri
        chunks: list[ProjectChunk] = []
        for index, paragraph in enumerate(text.split("\n\n")):
            cleaned = paragraph.strip()
            if not cleaned:
                continue
            chunks.append(
                self._build_chunk(
                    document=document,
                    text=cleaned,
                    chunk_index=index,
                    metadata={"section": str(index)},
                )
            )
        if not chunks:
            chunks.append(
                self._build_chunk(
                    document=document,
                    text=text,
                    chunk_index=0,
                    metadata={},
                )
            )
        return chunks

    async def build_payload(
        self,
        chunk: ProjectChunk,
        source: IngestSourceContent,
        *,
        config: Any | None = None,
    ) -> ProjectChunkPayload:
        del source, config
        return ProjectChunkPayload.from_chunk(chunk)

    def _build_chunk(
        self,
        *,
        document: ProjectDocument,
        text: str,
        chunk_index: int,
        metadata: dict[str, Any],
    ) -> ProjectChunk:
        return ProjectChunk(
            project_id=document.project_id,
            user_id=document.user_id,
            kb_id=document.kb_id,
            doc_id=document.doc_id,
            chunk_id=f"{document.doc_id}:{chunk_index}",
            chunk_index=chunk_index,
            text=text,
            data_type=document.data_type,
            visibility=document.visibility,
            content_hash=document.content_hash,
            embedding_version=document.embedding_version,
            chunker_version=document.chunker_version,
            metadata=metadata,
        )


def _content_hash(raw_content: bytes) -> str:
    return hashlib.sha256(raw_content).hexdigest()
