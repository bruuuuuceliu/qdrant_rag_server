"""Ingester contracts and prepared ingest data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ingestion_service import IngestionService
from retrieval_service.core.schemas import BaseChunk, BaseDocument


@dataclass(frozen=True, slots=True)
class PreparedIngestData:
    """Neutral or adapter-rendered data prepared during ingest."""

    document: Any
    chunks: tuple[Any, ...]
    payloads: tuple[Any, ...] = ()
    raw_content: bytes | None = None

    @property
    def texts(self) -> list[str]:
        return [str(getattr(chunk, "text", "")) for chunk in self.chunks]


class Ingester(Protocol):
    """Turns a file, URL, or ingest request into neutral document data."""

    async def prepare(
        self,
        request: Any,
        *,
        config: Any | None = None,
    ) -> PreparedIngestData:
        ...


class UniversalSourceIngester:
    """Compatibility wrapper around the standalone ingestion service."""

    async def prepare(
        self,
        request: Any,
        *,
        config: Any | None = None,
    ) -> PreparedIngestData:
        del config
        result = await IngestionService().process(request)
        metadata = dict(result.document.metadata)
        metadata.setdefault("raw_text", result.source.text())
        content_hash = str(metadata.get("content_hash") or result.document.content_hash)
        document = BaseDocument(
            document_id=result.document.document_id,
            source_uri=result.document.source_uri,
            content_type=result.document.content_type,
            data_type=result.document.data_type,
            content_hash=content_hash,
            metadata=metadata,
        )
        chunks = tuple(
            BaseChunk(
                document_id=document.document_id,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                data_type=chunk.data_type,
                content_hash=chunk.content_hash,
                chunker_version=chunk.chunker_version,
                metadata=dict(chunk.metadata),
            )
            for chunk in result.chunks
        )
        return PreparedIngestData(
            document=document,
            chunks=chunks,
            raw_content=result.raw_content,
        )


class AdapterBackedIngester:
    """Compatibility ingester for legacy adapters with ingest methods."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    async def prepare(
        self,
        request: Any,
        *,
        config: Any | None = None,
    ) -> PreparedIngestData:
        del config
        document = await self._adapter.parse_document(request)
        chunks = tuple(await self._adapter.build_chunks(document))
        payloads = tuple(
            [await self._adapter.build_payload(chunk) for chunk in chunks]
        )
        raw_content = _raw_content_from_document(document)
        return PreparedIngestData(
            document=document,
            chunks=chunks,
            payloads=payloads,
            raw_content=raw_content,
        )


def _raw_content_from_document(document: Any) -> bytes | None:
    metadata = getattr(document, "metadata", {}) or {}
    raw_content = metadata.get("raw_content")
    if raw_content is not None:
        if isinstance(raw_content, bytes):
            return raw_content
        if isinstance(raw_content, bytearray):
            return bytes(raw_content)
        return str(raw_content).encode("utf-8")
    raw_text = metadata.get("raw_text", "")
    if not raw_text:
        return None
    return str(raw_text).encode("utf-8")
