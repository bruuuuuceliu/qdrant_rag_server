"""Reusable ingest pipeline orchestration."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from retrieval_service.indexing.sparse_text import (
    _attach_sparse_text,
    _build_sparse_text,
)
from retrieval_service.ingest.ingester import AdapterBackedIngester, Ingester
from retrieval_service.pipeline.helpers import _encode_batch
from retrieval_service.retrieval.config import parse_retrieval_settings
from retrieval_service.services.entities import (
    NerExtractor,
    NoopNerExtractor,
    entities_to_metadata,
)
from retrieval_service.services.sparse_encoder import SparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._embedding_provider = embedding_provider
        self._qdrant_store = qdrant_store
        self._sparse_encoder = sparse_encoder
        self._ner_extractor = ner_extractor or NoopNerExtractor()
        self._object_storage = object_storage
        self._default_top_k = default_top_k
        self._default_candidate_count = default_candidate_count

    async def run(
        self,
        *,
        job_id: str,
        request: Any,
        config: Any,
        ingester: Ingester | None = None,
        adapter: Any | None = None,
    ) -> None:
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
        await self._store_raw_document(
            request=request,
            document=document,
            raw_content=prepared.raw_content,
        )

        settings = parse_retrieval_settings(
            config.retrieval_config,
            default_top_k=self._default_top_k,
            default_candidate_count=self._default_candidate_count,
        )

        if not chunks:
            logger.info("ingest job %s produced no chunks", job_id)
            return

        texts = [chunk.text for chunk in chunks]
        payloads = await self._enrich_payloads_with_entities(
            payloads,
            texts=texts,
            settings=settings,
        )
        vectors = None
        if settings.dense_enabled:
            vectors = await _encode_batch(self._embedding_provider, texts)

        if settings.bm25_enabled:
            if self._sparse_encoder is None:
                raise ValueError(
                    "BM25 retrieval is enabled but no sparse encoder is configured"
                )
            sparse_texts = [
                _build_sparse_text(
                    chunk.text,
                    getattr(chunk, "metadata", {}) or {},
                    lemmatize=settings.bm25.lemmatize,
                )
                for chunk in chunks
            ]
            sparse_vectors = await self._sparse_encoder.encode_batch(sparse_texts)
            payloads = _attach_sparse_text(
                payloads,
                sparse_texts,
                field_name=settings.bm25.text_field,
            )
            await self._qdrant_store.upsert_hybrid_points(
                collection_name=config.collection_name,
                dense_vectors=vectors,
                sparse_vectors=sparse_vectors,
                payloads=payloads,
                ids=[
                    str(getattr(payload, "chunk_id", index))
                    for index, payload in enumerate(payloads)
                ],
                dense_vector_name=settings.bm25.dense_vector_name,
                sparse_vector_name=settings.bm25.sparse_vector_name,
            )
        elif vectors is not None:
            await self._qdrant_store.upsert(
                collection_name=config.collection_name,
                vectors=vectors,
                payloads=payloads,
            )

        logger.info(
            "ingest job %s completed doc_id=%s chunks=%d",
            job_id,
            request.doc_id,
            len(chunks),
        )

    async def _store_raw_document(
        self,
        *,
        request: Any,
        document: Any,
        raw_content: bytes | None,
    ) -> None:
        if self._object_storage is None:
            return

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

    async def _enrich_payloads_with_entities(
        self,
        payloads: list[Any],
        *,
        texts: list[str],
        settings: Any,
    ) -> list[Any]:
        if not settings.ner.enabled:
            return payloads
        entities_by_chunk = await self._ner_extractor.extract_batch(texts)
        enriched: list[Any] = []
        for payload, entities in zip(payloads, entities_by_chunk):
            if not entities:
                enriched.append(payload)
                continue
            metadata = dict(getattr(payload, "metadata", {}) or {})
            metadata.update(entities_to_metadata(entities))
            enriched.append(replace(payload, metadata=metadata))
        return enriched
