"""Adapters from standalone ingestion output to retrieval payloads."""

from __future__ import annotations

from typing import Iterable

from ingestion_service import IngestedChunk
from retrieval_service.core.schemas import BaseChunkPayload


def payloads_from_ingested_chunks(
    chunks: Iterable[IngestedChunk],
    *,
    embedding_version: str = "",
) -> list[BaseChunkPayload]:
    """Render neutral ingestion chunks into retrieval payloads."""

    return [
        BaseChunkPayload(
            payload_id=chunk.chunk_id,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            data_type=chunk.data_type,
            content_hash=chunk.content_hash,
            embedding_version=embedding_version,
            chunker_version=chunk.chunker_version,
            metadata=dict(chunk.metadata),
        )
        for chunk in chunks
    ]
