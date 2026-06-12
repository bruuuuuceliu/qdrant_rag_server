"""RAG orchestrator for search, ingest, generation, and deletion."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from ingestion_service.jobs import MemoryIngestionJobRepository
from ingestion_service.jobs.sqlite import content_hash_from_metadata
from ingestion_service.schemas import IngestionJob
from retrieval_service.core.schemas import JobStatus
from project_service.gateway.plans import IngestPlan, SearchPlan
from retrieval_service.indexing import IndexingService
from retrieval_service.ingest.pipeline import IngestPipeline
from retrieval_service.ingest.workers import AsyncIngestWorkerQueue
from retrieval_service.pipeline.helpers import (
    _safe_str_attr,
)
from retrieval_service.retrieval.cache_keys import (
    _make_response_cache_key,
    _make_search_cache_key,
)
from retrieval_service.retrieval.config import parse_retrieval_settings
from retrieval_service.retrieval.factory import ProjectRetrieverFactory
from retrieval_service.retrieval.service import (
    DeleteDocumentRequest,
    RawDocumentRequest,
    RetrievalSearchRequest,
    RetrievalService,
)
from project_service.schemas import (
    GenerateResult,
    GenerationUnavailableError,
    IngestResult,
    ProjectConfig,
    SearchResult,
)
from retrieval_service.services.bm25 import BM25Index, BM25Retriever
from retrieval_service.services.entities import NerExtractor, NoopNerExtractor
from retrieval_service.services.retriever import QdrantVectorRetriever
from retrieval_service.services.sparse_encoder import SparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore
from shared.queue import QueueFullError, QueueMessage, QueueProducer

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_COUNT = 20
DEFAULT_TOP_K = 5


class IngestQueueFullError(QueueFullError):
    """Raised when the ingest queue cannot accept more jobs."""


def _ingestion_job_from_plan(job_id: str, plan: IngestPlan) -> IngestionJob:
    metadata = dict(plan.request.metadata)
    metadata.update(
        {
            "project_id": plan.request.project_id,
            "user_id": plan.request.user_id,
            "kb_id": plan.request.kb_id,
            "doc_id": plan.request.doc_id,
            "data_type": str(metadata.get("data_type", "project_document")),
            "content_hash": content_hash_from_metadata(metadata),
        }
    )
    return IngestionJob(
        job_id=job_id,
        source_uri=plan.request.source_uri,
        document_id=plan.request.doc_id,
        status=JobStatus.PENDING,
        metadata=metadata,
    )


def _job_to_ingest_result(job: IngestionJob) -> IngestResult:
    metadata = dict(job.metadata)
    return IngestResult(
        job_id=job.job_id,
        status=job.status,
        doc_id=str(metadata.get("doc_id", job.document_id)),
        project_id=str(metadata.get("project_id", "")),
        user_id=str(metadata.get("user_id", "")),
        kb_id=str(metadata.get("kb_id", "")),
        data_type=str(metadata.get("data_type", "project_document")),
        content_hash=str(metadata.get("content_hash", "")),
        raw_storage_key=str(metadata.get("raw_storage_key", "")),
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


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
        ingest_job_repository: Any = None,
        ingest_queue_maxsize: int = 0,
        bm25_index: BM25Index | None = None,
        sparse_encoder: SparseTextEncoder | None = None,
        ner_extractor: NerExtractor | None = None,
        retriever_factory: ProjectRetrieverFactory | None = None,
        retrieval_service: RetrievalService | None = None,
        indexing_service: IndexingService | None = None,
        ingest_event_publisher: QueueProducer | None = None,
        ingest_event_topic: str = "ingestion.events",
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
        self._ingest_event_publisher = ingest_event_publisher
        self._ingest_event_topic = ingest_event_topic
        self._retrieval_service = retrieval_service or RetrievalService(
            embedding_provider=self._embedding_provider,
            qdrant_store=self._qdrant_store,
            retriever_factory=self._retriever_factory,
            sparse_encoder=self._sparse_encoder,
            ner_extractor=self._ner_extractor,
            rerank_fn=self._rerank_fn,
            tier1_cache=self._tier1_cache,
            tier2_cache=self._tier2_cache,
            object_storage=self._object_storage,
            bm25_index=self._bm25_index,
            metrics=self._metrics,
            default_top_k=DEFAULT_TOP_K,
            default_candidate_count=DEFAULT_CANDIDATE_COUNT,
        )
        self._ingest_pipeline = IngestPipeline(
            embedding_provider=self._embedding_provider,
            qdrant_store=self._qdrant_store,
            sparse_encoder=self._sparse_encoder,
            ner_extractor=self._ner_extractor,
            object_storage=self._object_storage,
            default_top_k=DEFAULT_TOP_K,
            default_candidate_count=DEFAULT_CANDIDATE_COUNT,
            indexing_service=indexing_service,
        )
        self._ingest_jobs = ingest_job_repository or MemoryIngestionJobRepository()
        self._ingest_queue_runner = AsyncIngestWorkerQueue[IngestPlan](
            worker_count=ingest_worker_count,
            handler=self._process_ingest_job,
            maxsize=ingest_queue_maxsize,
            on_queue_depth=self._record_ingest_queue_depth,
        )
        self._ingest_queue = self._ingest_queue_runner.queue
        self._ingest_workers = self._ingest_queue_runner.workers
        self._ingest_status = getattr(self._ingest_jobs, "records", {})

    async def search(self, plan: SearchPlan) -> SearchResult:
        settings = parse_retrieval_settings(
            plan.config.retrieval_config,
            default_top_k=DEFAULT_TOP_K,
            default_candidate_count=DEFAULT_CANDIDATE_COUNT,
        )
        result = await self._retrieval_service.search(
            RetrievalSearchRequest(
                project_id=plan.config.project_id,
                user_id=plan.request.user_id,
                query_text=plan.request.query,
                collection_name=plan.config.collection_name,
                retrieval_config=dict(plan.config.retrieval_config),
                retrieval_filter=plan.retrieval_filter,
                cache_key=_make_search_cache_key(plan, settings),
            )
        )
        return SearchResult(
            chunks=result.chunks,
            elapsed_ms=result.elapsed_ms,
            cache_hit=result.cache_hit,
        )

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
            project_id=plan.request.project_id,
            user_id=plan.request.user_id,
            kb_id=plan.request.kb_id,
            data_type=str(plan.request.metadata.get("data_type", "project_document")),
            content_hash=content_hash_from_metadata(plan.request.metadata),
        )
        if self._metrics is not None:
            self._metrics.record_ingest_job()
        await self._ingest_jobs.create(_ingestion_job_from_plan(job_id, plan))
        await self._publish_ingest_event(
            event="ingest_scheduled",
            job_id=job_id,
            plan=plan,
            status=JobStatus.PENDING,
        )
        try:
            await self._ingest_queue_runner.submit(job_id, plan)
        except QueueFullError as exc:
            await self._ingest_jobs.update_status(
                job_id,
                JobStatus.FAILED,
                error="ingest queue is full",
            )
            if self._metrics is not None:
                self._metrics.record_ingest_job_failed()
            await self._publish_ingest_event(
                event="ingest_failed",
                job_id=job_id,
                plan=plan,
                status=JobStatus.FAILED,
                error="ingest queue is full",
            )
            raise IngestQueueFullError("ingest queue is full") from exc
        return result

    async def get_ingest_status(self, job_id: str) -> IngestResult | None:
        job = await self._ingest_jobs.get(job_id)
        if job is None:
            return None
        return _job_to_ingest_result(job)

    async def _process_ingest_job(self, job_id: str, plan: IngestPlan) -> None:
        await self._ingest_jobs.update_status(job_id, JobStatus.RUNNING)
        await self._publish_ingest_event(
            event="ingest_running",
            job_id=job_id,
            plan=plan,
            status=JobStatus.RUNNING,
        )
        try:
            pipeline_result = await self._run_ingest(job_id, plan)
        except Exception as exc:
            logger.exception("ingest job %s failed", job_id)
            await self._ingest_jobs.update_status(
                job_id,
                JobStatus.FAILED,
                error=str(exc),
            )
            if self._metrics is not None:
                self._metrics.record_ingest_job_failed()
            await self._publish_ingest_event(
                event="ingest_failed",
                job_id=job_id,
                plan=plan,
                status=JobStatus.FAILED,
                error=str(exc),
            )
            return

        await self._complete_indexed_ingest_job(job_id, plan, pipeline_result)

    async def _complete_indexed_ingest_job(
        self,
        job_id: str,
        plan: IngestPlan,
        pipeline_result: Any,
    ) -> None:
        try:
            await self._update_ingest_metadata(
                job_id,
                content_hash=pipeline_result.content_hash,
                raw_storage_key=pipeline_result.raw_storage_key,
            )
        except Exception:
            logger.exception("failed to update ingest metadata for indexed job %s", job_id)
        try:
            await self._ingest_jobs.update_status(job_id, JobStatus.COMPLETED)
        except Exception:
            logger.exception("failed to mark indexed ingest job %s completed", job_id)
        try:
            await self._invalidate_caches(plan)
        except Exception:
            logger.exception("failed to invalidate caches for indexed ingest job %s", job_id)
        await self._publish_ingest_event(
            event="ingest_completed",
            job_id=job_id,
            plan=plan,
            status=JobStatus.COMPLETED,
            content_hash=pipeline_result.content_hash,
            raw_storage_key=pipeline_result.raw_storage_key,
        )

    async def _run_ingest(self, job_id: str, plan: IngestPlan) -> Any:
        return await self._ingest_pipeline.run(
            job_id=job_id,
            request=plan.request,
            config=plan.config,
            ingester=plan.ingester,
            adapter=plan.adapter,
        )

    async def _update_ingest_metadata(
        self,
        job_id: str,
        *,
        content_hash: str = "",
        raw_storage_key: str = "",
    ) -> None:
        update_metadata = getattr(self._ingest_jobs, "update_metadata", None)
        if update_metadata is None:
            return
        metadata: dict[str, object] = {}
        if content_hash:
            metadata["content_hash"] = content_hash
        if raw_storage_key:
            metadata["raw_storage_key"] = raw_storage_key
        if metadata:
            await update_metadata(job_id, metadata)

    async def _invalidate_caches(self, plan: IngestPlan) -> None:
        project_id = plan.config.project_id
        user_id = plan.request.user_id

        if self._tier1_cache is not None:
            await self._tier1_cache.invalidate_project(project_id)
        if self._tier2_cache is not None:
            await self._tier2_cache.invalidate_user(project_id, user_id)

    async def _publish_ingest_event(
        self,
        *,
        event: str,
        job_id: str,
        plan: IngestPlan,
        status: JobStatus,
        error: str = "",
        content_hash: str = "",
        raw_storage_key: str = "",
    ) -> None:
        if self._ingest_event_publisher is None:
            return
        message = QueueMessage(
            topic=self._ingest_event_topic,
            key=job_id,
            payload={
                "event": event,
                "job_id": job_id,
                "status": status.value,
                "project_id": plan.request.project_id,
                "user_id": plan.request.user_id,
                "kb_id": plan.request.kb_id,
                "doc_id": plan.request.doc_id,
                "data_type": str(
                    plan.request.metadata.get("data_type", "project_document")
                ),
                "content_hash": content_hash,
                "raw_storage_key": raw_storage_key,
                "error": error,
            },
            headers={
                "project_id": plan.request.project_id,
                "user_id": plan.request.user_id,
                "correlation_id": job_id,
            },
        )
        try:
            await self._ingest_event_publisher.publish(message)
        except Exception:
            logger.exception(
                "failed to publish ingest event %s for job %s",
                event,
                job_id,
            )

    async def delete_document(
        self,
        *,
        config: ProjectConfig,
        user_id: str,
        kb_id: str,
        doc_id: str,
    ) -> None:
        await self._retrieval_service.delete_document(
            DeleteDocumentRequest(
                project_id=config.project_id,
                user_id=user_id,
                kb_id=kb_id,
                doc_id=doc_id,
                collection_name=config.collection_name,
            )
        )

    async def get_raw_document(
        self,
        *,
        project_id: str,
        user_id: str,
        doc_id: str,
    ) -> bytes | None:
        return await self._retrieval_service.get_raw_document(
            RawDocumentRequest(
                project_id=project_id,
                user_id=user_id,
                doc_id=doc_id,
            )
        )

    async def shutdown(self) -> None:
        await self._ingest_queue_runner.shutdown()

    def _record_ingest_queue_depth(self, depth: int) -> None:
        if self._metrics is not None:
            self._metrics.set_queue_depth(depth)
