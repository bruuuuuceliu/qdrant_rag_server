"""Ingester contracts and prepared ingest data."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from retrieval_service.core.schemas import BaseChunk, BaseDocument
from retrieval_service.ingest.source import load_ingest_source


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
    """Universal text ingester for raw text, local files, file URLs, and HTTP URLs."""

    async def prepare(
        self,
        request: Any,
        *,
        config: Any | None = None,
    ) -> PreparedIngestData:
        del config
        source = await load_ingest_source(request)
        metadata = dict(getattr(request, "metadata", {}) or {})
        metadata.setdefault("raw_text", source.text)
        content_hash = str(
            metadata.get("content_hash") or _content_hash(source.raw_content)
        )
        chunker_version = str(metadata.get("chunker_version", "v1"))
        document = BaseDocument(
            document_id=str(getattr(request, "doc_id", "")),
            source_uri=source.source_uri,
            content_type=source.content_type,
            data_type=str(metadata.get("data_type", "document")),
            content_hash=content_hash,
            metadata=metadata,
        )
        chunks = tuple(
            _chunk_document(
                document=document,
                text=source.text or source.source_uri,
                chunker_version=chunker_version,
            )
        )
        return PreparedIngestData(
            document=document,
            chunks=chunks,
            raw_content=source.raw_content,
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
    raw_text = metadata.get("raw_text", "")
    if not raw_text:
        return None
    return str(raw_text).encode("utf-8")


def _chunk_document(
    *,
    document: BaseDocument,
    text: str,
    chunker_version: str,
) -> list[BaseChunk]:
    chunks: list[BaseChunk] = []
    for index, paragraph in enumerate(text.split("\n\n")):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        chunks.append(
            BaseChunk(
                document_id=document.document_id,
                chunk_id=f"{document.document_id}:{index}",
                chunk_index=index,
                text=cleaned,
                data_type=document.data_type,
                content_hash=document.content_hash,
                chunker_version=chunker_version,
                metadata={"section": str(index)},
            )
        )
    if not chunks:
        chunks.append(
            BaseChunk(
                document_id=document.document_id,
                chunk_id=f"{document.document_id}:0",
                chunk_index=0,
                text=text,
                data_type=document.data_type,
                content_hash=document.content_hash,
                chunker_version=chunker_version,
            )
        )
    return chunks


def _content_hash(raw_content: bytes) -> str:
    return hashlib.sha256(raw_content).hexdigest()
