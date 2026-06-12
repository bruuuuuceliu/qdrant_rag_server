"""Reusable ingest pipeline orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from retrieval_service.indexing.service import (
    IndexChunksRequest,
    IndexingService,
)
from retrieval_service.ingest.ingester import AdapterBackedIngester, Ingester
from retrieval_service.services.entities import (
    NerExtractor,
    NoopNerExtractor,
)
from retrieval_service.services.sparse_encoder import SparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestPipelineResult:
    content_hash: str = ""
    raw_storage_key: str = ""


class IngestPipeline:
    """Parse, chunk, encode, and index one ingest request."""

    def __init__(
        self,
        *,
        embedding_provider: Any,
        qdrant_store: QdrantStore,
        sparse_encoder: SparseTextEncoder | None = None,
        ner_extractor: NerExtractor | None = None,
        object_storage: Any = None,
        default_top_k: int = 5,
        default_candidate_count: int = 20,
        indexing_service: IndexingService | None = None,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._qdrant_store = qdrant_store
        self._sparse_encoder = sparse_encoder
        self._ner_extractor = ner_extractor or NoopNerExtractor()
        self._object_storage = object_storage
        self._default_top_k = default_top_k
        self._default_candidate_count = default_candidate_count
        self._indexing_service = indexing_service or IndexingService(
            embedding_provider=self._embedding_provider,
            qdrant_store=self._qdrant_store,
            sparse_encoder=self._sparse_encoder,
            ner_extractor=self._ner_extractor,
            default_top_k=self._default_top_k,
            default_candidate_count=self._default_candidate_count,
        )

    async def run(
        self,
        *,
        job_id: str,
        request: Any,
        config: Any,
        ingester: Ingester | None = None,
        adapter: Any | None = None,
    ) -> IngestPipelineResult:
        if ingester is None:
            if adapter is None:
                raise ValueError("ingester is required")
            ingester = AdapterBackedIngester(adapter)

        prepared = await ingester.prepare(request, config=config)
        if adapter is not None and not prepared.payloads:
            prepared = await adapter.adapt_ingest_output(
                prepared,
                request,
                config=config,
            )
        document = prepared.document
        chunks = list(prepared.chunks)
        payloads = list(prepared.payloads)
        if len(chunks) != len(payloads):
            raise ValueError(
                "prepared ingest data must have matching chunk and payload counts"
            )
        raw_storage_key = await self._store_raw_document(
            request=request,
            document=document,
            raw_content=prepared.raw_content,
        )

        if not chunks:
            logger.info("ingest job %s produced no chunks", job_id)
            return IngestPipelineResult(
                content_hash=str(getattr(document, "content_hash", "") or ""),
                raw_storage_key=raw_storage_key,
            )

        await self._indexing_service.index_chunks(
            IndexChunksRequest(
                collection_name=config.collection_name,
                chunks=chunks,
                payloads=payloads,
                retrieval_config=dict(config.retrieval_config),
                job_id=job_id,
            )
        )

        logger.info(
            "ingest job %s completed doc_id=%s chunks=%d",
            job_id,
            request.doc_id,
            len(chunks),
        )
        return IngestPipelineResult(
            content_hash=str(getattr(document, "content_hash", "") or ""),
            raw_storage_key=raw_storage_key,
        )

    async def _store_raw_document(
        self,
        *,
        request: Any,
        document: Any,
        raw_content: bytes | None,
    ) -> str:
        if self._object_storage is None:
            return ""

        from retrieval_service.storage.base import make_storage_key

        storage_key = make_storage_key(
            request.project_id,
            request.user_id,
            request.doc_id,
        )
        if raw_content is None:
            raw_text = document.metadata.get("raw_text", "")
            raw_content = raw_text.encode("utf-8")
        if raw_content:
            await self._object_storage.put(
                storage_key,
                raw_content,
                content_type=request.content_type,
            )
            logger.debug("stored raw document %s", storage_key)
            return storage_key
        return ""
