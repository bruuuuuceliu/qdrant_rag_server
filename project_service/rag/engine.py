"""RAG orchestrator for search, ingest, generation, and deletion."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import replace
from typing import Any

from retrieval_service.core.schemas import JobStatus
from project_service.gateway.plans import IngestPlan, SearchPlan
from project_service.rag.cache_keys import (
    _make_response_cache_key,
    _make_search_cache_key,
)
from project_service.rag.filters import _build_qdrant_filter
from project_service.rag.entity_boost import (
    apply_entity_boosts,
    extract_query_entity_keys,
)
from project_service.rag.helpers import (
    _elapsed_ms,
    _encode_batch,
    _encode_query,
    _safe_str_attr,
)
from project_service.rag.retrieval_config import (
    ProjectRetrievalSettings,
    parse_retrieval_settings,
)
from project_service.rag.retriever_factory import ProjectRetrieverFactory
from project_service.schemas import (
    GenerateResult,
    GenerationUnavailableError,
    IngestResult,
    ProjectConfig,
    SearchResult,
)
from retrieval_service.services.bm25 import BM25Index, BM25Retriever
from retrieval_service.services.entities import (
    EntityMention,
    NerExtractor,
    NoopNerExtractor,
    entities_to_metadata,
)
from retrieval_service.services.retriever import QdrantVectorRetriever, RetrievalQuery
from retrieval_service.services.retriever import RetrievalHit, Retriever
from retrieval_service.services.sparse_encoder import SparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_COUNT = 20
DEFAULT_TOP_K = 5


class RagEngine:
    """Orchestrates retrieval and ingestion."""

    def __init__(
        self,
        *,
        embedding_provider: Any = None,
        embed_fn: Any = None,
        qdrant_store: QdrantStore,
        rerank_fn: Any = None,
        tier1_cache: Any = None,
        tier2_cache: Any = None,
        openrouter_client: Any = None,
        retriever: Any = None,
        version_manager: Any = None,
        metrics: Any = None,
        object_storage: Any = None,
        bm25_index: BM25Index | None = None,
        sparse_encoder: SparseTextEncoder | None = None,
        ner_extractor: NerExtractor | None = None,
        retriever_factory: ProjectRetrieverFactory | None = None,
        ingest_worker_count: int = 4,
    ) -> None:
        if embedding_provider is None and embed_fn is None:
            raise ValueError("embedding_provider is required")
        self._embedding_provider = (
            embedding_provider if embedding_provider is not None else embed_fn
        )
        self._qdrant_store = qdrant_store
        dense_retriever = retriever or QdrantVectorRetriever(qdrant_store)
        bm25_retriever = BM25Retriever(bm25_index) if bm25_index is not None else None
        self._retriever = dense_retriever
        self._retriever_factory = retriever_factory or ProjectRetrieverFactory(
            dense_retriever=dense_retriever,
            bm25_retriever=bm25_retriever,
        )
        self._bm25_index = bm25_index
        self._sparse_encoder = sparse_encoder
        self._ner_extractor = ner_extractor or NoopNerExtractor()
        self._rerank_fn = rerank_fn
        self._tier1_cache = tier1_cache
        self._tier2_cache = tier2_cache
        self._openrouter = openrouter_client
        self._version_manager = version_manager
        self._metrics = metrics
        self._object_storage = object_storage
        self._ingest_queue: asyncio.Queue[tuple[str, IngestPlan]] = asyncio.Queue()
        self._ingest_status: dict[str, IngestResult] = {}
        self._ingest_workers = [
            asyncio.create_task(self._ingest_loop())
            for _ in range(ingest_worker_count)
        ]

    async def search(self, plan: SearchPlan) -> SearchResult:
        start_ns = time.monotonic_ns()

        if self._metrics is not None:
            self._metrics.record_search_request()

        config = plan.config
        settings = parse_retrieval_settings(
            config.retrieval_config,
            default_top_k=DEFAULT_TOP_K,
            default_candidate_count=DEFAULT_CANDIDATE_COUNT,
        )
        cache_key = _make_search_cache_key(plan, settings)

        if self._tier1_cache is not None:
            cached = await self._tier1_cache.get(
                plan.config.project_id, cache_key
            )
            if cached is not None:
                cached = dict(cached)
                cached["cache_hit"] = True
                if self._metrics is not None:
                    self._metrics.record_search_cache_hit()
                    latency_ms = (time.monotonic_ns() - start_ns) / 1e6
                    self._metrics.record_search_latency(latency_ms)
                cached["elapsed_ms"] = max(1, _elapsed_ms(start_ns))
                return SearchResult(**cached)

        top_k = settings.top_k
        candidate_count = settings.candidate_count

        qdrant_filter = _build_qdrant_filter(plan.retrieval_filter)
        query_vector = None
        if settings.dense_enabled:
            query_vector = await _encode_query(
                self._embedding_provider,
                plan.request.query,
            )
        query_sparse_vector = None
        if settings.bm25_enabled:
            if self._sparse_encoder is None:
                raise ValueError(
                    "BM25 retrieval is enabled but no sparse encoder is configured"
                )
            query_sparse_vector = await self._sparse_encoder.encode(
                _build_sparse_text(
                    plan.request.query,
                    {},
                    lemmatize=settings.bm25.lemmatize,
                )
            )

        search_results = await self._search_candidates(
            query=RetrievalQuery(
                collection_name=config.collection_name,
                query_text=plan.request.query,
                query_vector=query_vector,
                query_sparse_vector=query_sparse_vector,
                retrieval_filter=qdrant_filter,
                limit=candidate_count,
                metadata={
                    "filter_fields": self._build_filter_fields(plan.retrieval_filter),
                    "dense_vector_name": (
                        settings.bm25.dense_vector_name
                        if settings.bm25_enabled
                        else None
                    ),
                },
            ),
            settings=settings,
        )
        if settings.ner.enabled and settings.ner.boost_entities:
            query_entities = await self._extract_query_entities(
                query_text=plan.request.query,
                settings=settings,
            )
            search_results = apply_entity_boosts(
                search_results,
                query_entity_keys=extract_query_entity_keys(
                    query_entities=query_entities
                ),
                boost=settings.ner.entity_boost,
            )

        if self._rerank_fn is not None and len(search_results) > 0:
            pairs = [
                (hit.payload, hit.score)
                for hit in search_results
                if hit.payload is not None
            ]
            reranked = await self._rerank_fn(plan.request.query, pairs)
            final = reranked[:top_k]
        else:
            final = [
                (hit.payload, hit.score)
                for hit in search_results[:top_k]
                if hit.payload
            ]

        chunks: list[dict[str, Any]] = []
        for payload_data, score in final:
            chunk = dict(payload_data) if isinstance(payload_data, dict) else {}
            chunk["score"] = score
            chunks.append(chunk)

        elapsed_ms = max(1, _elapsed_ms(start_ns))
        result = SearchResult(chunks=chunks, elapsed_ms=elapsed_ms, cache_hit=False)

        if self._tier1_cache is not None:
            await self._tier1_cache.set(
                config.project_id,
                cache_key,
                {"chunks": chunks, "elapsed_ms": result.elapsed_ms},
            )

        if self._metrics is not None:
            latency_ms = (time.monotonic_ns() - start_ns) / 1e6
            self._metrics.record_search_latency(latency_ms)

        return result

    async def generate(
        self,
        *,
        project_id: str,
        user_id: str,
        query: str,
        chunks: list[dict[str, Any]],
        openrouter_key: str,
        model: str | None = None,
    ) -> GenerateResult:
        if self._metrics is not None:
            self._metrics.record_generate_request()

        if self._openrouter is None:
            raise GenerationUnavailableError(
                "generation is disabled for this deployment"
            )

        cache_key = _make_response_cache_key(
            project_id,
            user_id,
            query,
            chunks,
            provider=_safe_str_attr(self._openrouter, "provider_name"),
            model=model or _safe_str_attr(self._openrouter, "default_model"),
        )

        if self._tier2_cache is not None:
            cached_response = await self._tier2_cache.get(
                project_id, user_id, cache_key
            )
            if cached_response is not None:
                if self._metrics is not None:
                    self._metrics.record_generate_cache_hit()
                return GenerateResult(response=cached_response, cache_hit=True)

        context_parts = [c.get("text", "") for c in chunks]
        context = "\n\n---\n\n".join(context_parts)

        prompt = (
            "You are a helpful assistant. Answer the question based only on the provided context.\n"
            "If the answer is not in the context, say 'I don't have enough information to answer that.'\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {query}\n\n"
            "Answer:"
        )

        result = await self._openrouter.generate_response(
            messages=[{"role": "user", "content": prompt}],
            api_key=openrouter_key,
            model=model,
        )

        if self._tier2_cache is not None:
            await self._tier2_cache.set(project_id, user_id, cache_key, result)

        return GenerateResult(response=result, cache_hit=False)

    async def schedule_ingest(self, plan: IngestPlan) -> IngestResult:
        job_id = str(uuid.uuid4())
        result = IngestResult(
            job_id=job_id,
            status=JobStatus.PENDING,
            doc_id=plan.request.doc_id,
        )
        if self._metrics is not None:
            self._metrics.record_ingest_job()
        self._ingest_status[job_id] = result
        await self._ingest_queue.put((job_id, plan))
        if self._metrics is not None:
            self._metrics.set_queue_depth(self._ingest_queue.qsize())
        return result

    async def get_ingest_status(self, job_id: str) -> IngestResult | None:
        return self._ingest_status.get(job_id)

    async def _ingest_loop(self) -> None:
        while True:
            try:
                job_id, plan = await self._ingest_queue.get()
            except asyncio.CancelledError:
                return

            result = self._ingest_status.get(job_id)
            if result is not None:
                result.status = JobStatus.RUNNING
                result.updated_at = time.time()

            try:
                await self._run_ingest(job_id, plan)
                if result is not None:
                    result.status = JobStatus.COMPLETED
                    result.error = None
                    result.updated_at = time.time()
                await self._invalidate_caches(plan)
            except Exception as exc:
                logger.exception("ingest job %s failed", job_id)
                if result is not None:
                    result.status = JobStatus.FAILED
                    result.error = str(exc)
                    result.updated_at = time.time()
                if self._metrics is not None:
                    self._metrics.record_ingest_job_failed()
            finally:
                self._ingest_queue.task_done()
                if self._metrics is not None:
                    self._metrics.set_queue_depth(self._ingest_queue.qsize())

    async def _run_ingest(self, job_id: str, plan: IngestPlan) -> None:
        adapter = plan.adapter
        config = plan.config
        request = plan.request

        document = await adapter.parse_document(request)

        if self._object_storage is not None:
            from retrieval_service.storage.base import make_storage_key

            storage_key = make_storage_key(
                request.project_id, request.user_id, request.doc_id
            )
            raw_content = document.metadata.get("raw_text", "").encode("utf-8")
            if raw_content:
                await self._object_storage.put(
                    storage_key, raw_content, content_type=request.content_type
                )
                logger.debug("stored raw document %s", storage_key)

        settings = parse_retrieval_settings(
            config.retrieval_config,
            default_top_k=DEFAULT_TOP_K,
            default_candidate_count=DEFAULT_CANDIDATE_COUNT,
        )
        chunks = await adapter.build_chunks(document)

        if not chunks:
            logger.info("ingest job %s produced no chunks", job_id)
            return

        chunks = await self._enrich_chunks_with_entities(chunks, settings=settings)

        payloads = [
            await adapter.build_payload(chunk)
            for chunk in chunks
        ]

        texts = [chunk.text for chunk in chunks]
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
                ids=[str(getattr(payload, "chunk_id", index)) for index, payload in enumerate(payloads)],
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

    async def _invalidate_caches(self, plan: IngestPlan) -> None:
        project_id = plan.config.project_id
        user_id = plan.request.user_id

        if self._tier1_cache is not None:
            await self._tier1_cache.invalidate_project(project_id)
        if self._tier2_cache is not None:
            await self._tier2_cache.invalidate_user(project_id, user_id)

    async def delete_document(
        self,
        *,
        config: ProjectConfig,
        user_id: str,
        kb_id: str,
        doc_id: str,
    ) -> None:
        project_id = config.project_id
        await self._qdrant_store.delete_document(
            collection_name=config.collection_name,
            project_id=project_id,
            user_id=user_id,
            kb_id=kb_id,
            doc_id=doc_id,
        )
        if self._object_storage is not None:
            from retrieval_service.storage.base import make_storage_key

            storage_key = make_storage_key(project_id, user_id, doc_id)
            await self._object_storage.delete(storage_key)

        if self._tier1_cache is not None:
            await self._tier1_cache.invalidate_project(project_id)
        if self._tier2_cache is not None:
            await self._tier2_cache.invalidate_user(project_id, user_id)

    async def get_raw_document(
        self,
        *,
        project_id: str,
        user_id: str,
        doc_id: str,
    ) -> bytes | None:
        if self._object_storage is None:
            return None

        from retrieval_service.storage.base import ObjectStorageError, make_storage_key

        storage_key = make_storage_key(project_id, user_id, doc_id)
        try:
            return await self._object_storage.get(storage_key)
        except ObjectStorageError:
            return None

    async def shutdown(self) -> None:
        for worker in self._ingest_workers:
            worker.cancel()
        await asyncio.gather(*self._ingest_workers, return_exceptions=True)

    async def _search_candidates(
        self,
        *,
        query: RetrievalQuery,
        settings: ProjectRetrievalSettings,
    ) -> list[RetrievalHit]:
        retriever: Retriever = self._retriever_factory.build(settings=settings)
        return await retriever.search(query)

    async def _extract_query_entities(
        self,
        *,
        query_text: str,
        settings: ProjectRetrievalSettings,
    ) -> list[EntityMention]:
        if not settings.ner.enabled or not settings.ner.boost_entities:
            return []
        return await self._ner_extractor.extract(query_text)

    async def _enrich_chunks_with_entities(
        self,
        chunks: list[Any],
        *,
        settings: ProjectRetrievalSettings,
    ) -> list[Any]:
        if not settings.ner.enabled:
            return chunks
        entities_by_chunk = await self._ner_extractor.extract_batch(
            [chunk.text for chunk in chunks]
        )
        enriched: list[Any] = []
        for chunk, entities in zip(chunks, entities_by_chunk):
            if not entities:
                enriched.append(chunk)
                continue
            metadata = dict(getattr(chunk, "metadata", {}) or {})
            metadata.update(entities_to_metadata(entities))
            enriched.append(replace(chunk, metadata=metadata))
        return enriched

    def _build_filter_fields(
        self,
        retrieval_filter: Any,
    ) -> dict[str, str | tuple[str, ...]]:
        fields: dict[str, str | tuple[str, ...]] = {
            "project_id": retrieval_filter.project_id,
            "user_id": tuple(retrieval_filter.allowed_user_ids),
        }
        if getattr(retrieval_filter, "kb_ids", ()):
            fields["kb_id"] = tuple(retrieval_filter.kb_ids)
        if getattr(retrieval_filter, "doc_ids", ()):
            fields["doc_id"] = tuple(retrieval_filter.doc_ids)
        return fields


def _build_sparse_text(
    text: str,
    metadata: dict[str, Any],
    *,
    lemmatize: bool,
) -> str:
    del metadata
    normalized = " ".join(text.split())
    if lemmatize:
        return normalized.casefold()
    return normalized


def _attach_sparse_text(
    payloads: list[Any],
    sparse_texts: list[str],
    *,
    field_name: str,
) -> list[Any]:
    return [
        _SparsePayload(payload=payload, field_name=field_name, sparse_text=sparse_text)
        for payload, sparse_text in zip(payloads, sparse_texts)
    ]


class _SparsePayload:
    def __init__(self, *, payload: Any, field_name: str, sparse_text: str) -> None:
        self._payload = payload
        self._field_name = field_name
        self._sparse_text = sparse_text

    def to_qdrant_payload(self) -> dict[str, Any]:
        rendered = dict(self._payload.to_qdrant_payload())
        rendered[self._field_name] = self._sparse_text
        return rendered

    def point_identity(self) -> tuple[str, ...]:
        return self._payload.point_identity()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._payload, name)
