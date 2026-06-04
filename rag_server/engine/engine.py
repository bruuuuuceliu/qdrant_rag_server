"""RAG engine - orchestrates the full search and ingest pipelines.

The engine is the bridge between gateway validation and backend services
(embedding, Qdrant, reranker).  It receives validated ``SearchPlan`` and
``IngestPlan`` objects from the gateway and coordinates the actual work.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import models as qdrant_models

from rag_server.gateway.handler import SearchPlan, IngestPlan
from rag_server.core.models import (
    BaseChunkPayload,
    BaseRetrievalFilter,
    IngestJobStatus,
    SHARED_USER_ID,
)
from rag_server.services.vector_store import QdrantStore

logger = logging.getLogger(__name__)


DEFAULT_CANDIDATE_COUNT = 20
DEFAULT_TOP_K = 5


@dataclass
class SearchResult:
    chunks: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    cache_hit: bool = False


@dataclass
class IngestResult:
    job_id: str
    status: IngestJobStatus


@dataclass
class GenerateResult:
    response: str
    cache_hit: bool


def _make_search_cache_key(plan: SearchPlan) -> str:
    components = [
        plan.request.project_id,
        plan.request.user_id,
        plan.request.query,
        ",".join(sorted(plan.request.kb_ids)),
        str(plan.request.include_shared),
        plan.config.active_embedding_version,
    ]
    return hashlib.sha256("|".join(components).encode()).hexdigest()


def _make_response_cache_key(
    project_id: str, user_id: str, query: str, chunks: list[dict[str, Any]]
) -> str:
    chunk_sig = "|".join(
        sorted(c.get("chunk_id", "") for c in chunks)
    )
    raw = f"{project_id}|{user_id}|{query}|{chunk_sig}"
    return hashlib.sha256(raw.encode()).hexdigest()


class RagEngine:
    """Orchestrates retrieval and ingestion."""

    def __init__(
        self,
        *,
        embed_fn: Any,
        qdrant_store: QdrantStore,
        rerank_fn: Any = None,
        tier1_cache: Any = None,
        tier2_cache: Any = None,
        openrouter_client: Any = None,
        version_manager: Any = None,
        metrics: Any = None,
        object_storage: Any = None,
        ingest_worker_count: int = 4,
    ) -> None:
        self._embed_fn = embed_fn
        self._qdrant_store = qdrant_store
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
        import time as _time
        start_ns = _time.monotonic_ns()

        if self._metrics is not None:
            self._metrics.record_search_request()

        cache_key = _make_search_cache_key(plan)

        if self._tier1_cache is not None:
            cached = await self._tier1_cache.get(
                plan.config.project_id, cache_key
            )
            if cached is not None:
                cached["cache_hit"] = True
                if self._metrics is not None:
                    self._metrics.record_search_cache_hit()
                    latency_ms = (_time.monotonic_ns() - start_ns) / 1e6
                    self._metrics.record_search_latency(latency_ms)
                return SearchResult(**cached)

        config = plan.config
        top_k = int(config.retrieval_config.get("top_k", DEFAULT_TOP_K))
        candidate_count = int(
            config.retrieval_config.get("candidate_count", DEFAULT_CANDIDATE_COUNT)
        )

        query_vector = await self._embed_fn(plan.request.query)

        qdrant_filter = _build_qdrant_filter(plan.retrieval_filter)

        search_results = await self._qdrant_store.search(
            collection_name=config.collection_name,
            query_vector=query_vector,
            query_filter=qdrant_filter,
            limit=candidate_count,
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
                if hit.payload is not None
            ]

        chunks: list[dict[str, Any]] = []
        for payload_data, score in final:
            chunk = dict(payload_data) if isinstance(payload_data, dict) else {}
            chunk["score"] = score
            chunks.append(chunk)

        result = SearchResult(chunks=chunks, cache_hit=False)

        if self._tier1_cache is not None:
            await self._tier1_cache.set(
                config.project_id,
                cache_key,
                {"chunks": chunks, "elapsed_ms": result.elapsed_ms},
            )

        if self._metrics is not None:
            latency_ms = (_time.monotonic_ns() - start_ns) / 1e6
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

        cache_key = _make_response_cache_key(
            project_id, user_id, query, chunks
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

        result = await self._openrouter.generate(
            prompt=prompt,
            api_key=openrouter_key,
            model=model or "openai/gpt-4o-mini",
        )

        if self._tier2_cache is not None:
            await self._tier2_cache.set(
                project_id, user_id, cache_key, result
            )

        return GenerateResult(response=result, cache_hit=False)

    async def schedule_ingest(self, plan: IngestPlan) -> IngestResult:
        job_id = str(uuid.uuid4())
        result = IngestResult(job_id=job_id, status=IngestJobStatus.PENDING)
        if self._metrics is not None:
            self._metrics.record_ingest_job()
        self._ingest_status[job_id] = result
        await self._ingest_queue.put((job_id, plan))
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
                result.status = IngestJobStatus.RUNNING

            try:
                await self._run_ingest(job_id, plan)
                if result is not None:
                    result.status = IngestJobStatus.COMPLETED
                await self._invalidate_caches(plan)
            except Exception as exc:
                logger.exception("ingest job %s failed", job_id)
                if result is not None:
                    result.status = IngestJobStatus.FAILED
                if self._metrics is not None:
                    self._metrics.record_ingest_job_failed()

    async def _run_ingest(self, job_id: str, plan: IngestPlan) -> None:
        adapter = plan.adapter
        config = plan.config
        request = plan.request

        document = await adapter.parse_document(request)

        if self._object_storage is not None:
            from rag_server.storage.base import make_storage_key

            storage_key = make_storage_key(
                request.project_id, request.user_id, request.doc_id
            )
            raw_content = document.metadata.get("raw_text", "").encode("utf-8")
            if raw_content:
                await self._object_storage.put(
                    storage_key, raw_content, content_type=request.content_type
                )
                logger.debug("stored raw document %s", storage_key)

        chunks = await adapter.build_chunks(document)

        if not chunks:
            logger.info("ingest job %s produced no chunks", job_id)
            return

        texts = [chunk.text for chunk in chunks]
        vectors = await self._embed_fn.encode_batch(texts)

        payloads = [
            await adapter.build_payload(chunk)
            for chunk in chunks
        ]

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
        project_id: str,
        user_id: str,
        doc_id: str,
        collection_name: str,
    ) -> None:
        await self._qdrant_store.delete_document(collection_name, doc_id)

        if self._object_storage is not None:
            from rag_server.storage.base import make_storage_key

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

        from rag_server.storage.base import make_storage_key, ObjectStorageError

        storage_key = make_storage_key(project_id, user_id, doc_id)
        try:
            return await self._object_storage.get(storage_key)
        except ObjectStorageError:
            return None

    async def shutdown(self) -> None:
        for worker in self._ingest_workers:
            worker.cancel()
        await asyncio.gather(*self._ingest_workers, return_exceptions=True)


def _build_qdrant_filter(
    retrieval_filter: BaseRetrievalFilter,
) -> qdrant_models.Filter:
    must: list[qdrant_models.Condition] = []

    must.append(
        qdrant_models.FieldCondition(
            key="project_id",
            match=qdrant_models.MatchValue(value=retrieval_filter.project_id),
        )
    )

    user_ids = retrieval_filter.allowed_user_ids
    if len(user_ids) == 1:
        must.append(
            qdrant_models.FieldCondition(
                key="user_id",
                match=qdrant_models.MatchValue(value=user_ids[0]),
            )
        )
    else:
        must.append(
            qdrant_models.FieldCondition(
                key="user_id",
                match=qdrant_models.MatchAny(any=list(user_ids)),
            )
        )

    if retrieval_filter.kb_ids:
        if len(retrieval_filter.kb_ids) == 1:
            must.append(
                qdrant_models.FieldCondition(
                    key="kb_id",
                    match=qdrant_models.MatchValue(value=retrieval_filter.kb_ids[0]),
                )
            )
        else:
            must.append(
                qdrant_models.FieldCondition(
                    key="kb_id",
                    match=qdrant_models.MatchAny(any=list(retrieval_filter.kb_ids)),
                )
            )

    if retrieval_filter.doc_ids:
        if len(retrieval_filter.doc_ids) == 1:
            must.append(
                qdrant_models.FieldCondition(
                    key="doc_id",
                    match=qdrant_models.MatchValue(value=retrieval_filter.doc_ids[0]),
                )
            )
        else:
            must.append(
                qdrant_models.FieldCondition(
                    key="doc_id",
                    match=qdrant_models.MatchAny(any=list(retrieval_filter.doc_ids)),
                )
            )

    return qdrant_models.Filter(must=must)
