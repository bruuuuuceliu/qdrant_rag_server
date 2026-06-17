"""Local application bootstrap for the retrieval gRPC server."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from configs import AppSettings, load_settings


@dataclass(slots=True)
class AppContext:
    settings: AppSettings
    config_repo: object
    gateway: object
    engine: object
    project_client: object
    embedding_provider: object
    qdrant_store: object
    bm25_index: object | None
    sparse_encoder: object | None
    ner_extractor: object | None
    metrics: object
    ingest_event_broker: object
    reranker: object | None
    object_storage: object
    version_manager: object
    workflow_log_app: object
    health_checker: object
    openrouter_client: object | None
    server: object

    async def shutdown(self) -> None:
        await self.server.stop(grace=5)
        await self.workflow_log_app.shutdown()
        await self.engine.shutdown()
        if self.openrouter_client is not None:
            await self.openrouter_client.shutdown()
        if self.reranker is not None:
            await self.reranker.shutdown()
        await self.embedding_provider.shutdown()
        if self.bm25_index is not None:
            await self.bm25_index.close()
        await self.qdrant_store.close()


async def create_app(
    settings: AppSettings | None = None,
    *,
    start_server: bool = True,
) -> AppContext:
    settings = settings or load_settings()

    from project_service.adapters import (
        ProjectAdapterRegistry,
        ProjectAdapterResolver,
        WebsiteProjectAdapter,
    )
    from project_service.config import SQLiteProjectConfigRepository
    from project_service.client import LocalProjectServiceClient
    from project_service.rag.engine import RagEngine
    from project_service.gateway import AsyncConcurrencyLimiter, RagGateway
    from ingestion_service.jobs import SQLiteIngestionJobRepository
    from retrieval_service.health import HealthChecker, MetricsCollector
    from retrieval_service.services.cache import Tier1MemoryCache, Tier2ResponseCache
    from retrieval_service.embedding import EmbeddingProviderFactory
    from retrieval_service.llm import LLMProviderFactory
    from retrieval_service.services.bm25 import QdrantSparseBM25Index
    from retrieval_service.services.entities import LocalNerExtractor, NoopNerExtractor
    from retrieval_service.services.reranker import RerankerService
    from retrieval_service.services.sparse_encoder import FastEmbedSparseTextEncoder
    from retrieval_service.services.vector_store import QdrantStore
    from retrieval_service.storage.filesystem import FilesystemObjectStorage
    from retrieval_service.storage.memory import MemoryObjectStorage
    from shared.queue import LocalQueueBroker
    from project_service.versioning.manager import VersionManager
    from workflow_log_service.server import create_app as create_workflow_log_app
    serve_grpc = _resolve_serve_grpc()

    config_repo = SQLiteProjectConfigRepository(settings.config_db_path)
    await config_repo.initialize()

    registry = ProjectAdapterRegistry()
    registry.register(WebsiteProjectAdapter(config_repo=config_repo))
    gateway = RagGateway(
        adapter_resolver=ProjectAdapterResolver(
            project_types=config_repo,
            registry=registry,
        ),
        concurrency_limiter=AsyncConcurrencyLimiter(
            max_per_project=settings.max_per_project,
            max_per_user=settings.max_per_user,
        ),
    )

    embedding_provider = _build_embedding_provider(
        settings,
        factory=EmbeddingProviderFactory,
    )
    await embedding_provider.initialize()

    qdrant_store = QdrantStore(
        url=settings.qdrant_url,
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        default_vector_size=settings.embedding_dimension,
    )
    tier2_cache = Tier2ResponseCache(settings.response_cache_db_path)
    await tier2_cache.initialize()
    tier1_cache = Tier1MemoryCache()
    metrics = MetricsCollector()
    ingest_event_broker = LocalQueueBroker(
        maxsize=settings.ingest_event_queue_maxsize,
    )
    workflow_log_app = await create_workflow_log_app(
        queue=ingest_event_broker,
        enabled=settings.workflow_log_enabled,
        topic=settings.workflow_log_topic,
        db_path=settings.workflow_log_db_path,
    )
    ingest_job_repository = SQLiteIngestionJobRepository(settings.ingest_job_db_path)
    await ingest_job_repository.initialize()
    openrouter_client = _build_llm_provider(settings, factory=LLMProviderFactory)
    if openrouter_client is not None:
        await openrouter_client.initialize()
    sparse_encoder = FastEmbedSparseTextEncoder(settings.bm25_encoder_model)
    bm25_index = QdrantSparseBM25Index(
        store=qdrant_store,
        sparse_vector_name=settings.bm25_sparse_vector_name,
    )
    await bm25_index.initialize()
    ner_extractor = NoopNerExtractor()
    if settings.ner_provider == "local":
        ner_extractor = LocalNerExtractor(settings.ner_model)
        await ner_extractor.initialize()

    # Optional reranker
    rerank_fn = None
    reranker = None
    if settings.rerank_enabled:
        reranker = RerankerService(
            model_name=settings.rerank_model,
            device=settings.rerank_device,
        )
        rerank_fn = await reranker.initialize()

    # Object storage (filesystem for local dev, memory as fallback)
    if settings.object_storage_provider == "filesystem":
        object_storage = FilesystemObjectStorage(settings.object_storage_base_path)
    else:
        from retrieval_service.storage.memory import MemoryObjectStorage
        object_storage = MemoryObjectStorage()

    # Version manager
    version_manager = VersionManager(config_repo=config_repo)
    await version_manager.initialize()

    engine = RagEngine(
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
        bm25_index=bm25_index,
        ner_extractor=ner_extractor,
        tier1_cache=tier1_cache,
        tier2_cache=tier2_cache,
        openrouter_client=openrouter_client,
        metrics=metrics,
        ingest_job_repository=ingest_job_repository,
        ingest_queue_maxsize=settings.ingest_queue_maxsize,
        ingest_event_publisher=ingest_event_broker,
        ingest_event_topic=settings.ingest_event_topic,
        sparse_encoder=sparse_encoder,
        ingest_worker_count=settings.ingest_worker_count,
        max_concurrent_searches=settings.max_concurrent_searches,
        max_concurrent_ingest_schedules=settings.max_concurrent_ingest_schedules,
        rerank_fn=rerank_fn,
        object_storage=object_storage,
        version_manager=version_manager,
    )
    project_client = LocalProjectServiceClient(gateway=gateway, engine=engine)
    health_checker = HealthChecker(
        qdrant_store=qdrant_store,
        embed_fn=embedding_provider,
        tier1_cache=tier1_cache,
        tier2_cache=tier2_cache,
        config_repo=config_repo,
        openrouter_client=openrouter_client,
    )
    if start_server:
        server = await serve_grpc(
            gateway=gateway,
            engine=engine,
            health_checker=health_checker,
            port=settings.grpc_port,
        )
    else:
        server = _NoopServer()
    return AppContext(
        settings=settings,
        config_repo=config_repo,
        gateway=gateway,
        engine=engine,
        project_client=project_client,
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
        bm25_index=bm25_index,
        sparse_encoder=sparse_encoder,
        ner_extractor=ner_extractor,
        metrics=metrics,
        ingest_event_broker=ingest_event_broker,
        workflow_log_app=workflow_log_app,
        health_checker=health_checker,
        openrouter_client=openrouter_client,
        server=server,
        reranker=reranker,
        object_storage=object_storage,
        version_manager=version_manager,
    )


async def serve_forever(settings: AppSettings | None = None) -> None:
    app = await create_app(settings)
    try:
        await app.server.wait_for_termination()
    finally:
        await app.shutdown()


def main() -> None:
    asyncio.run(serve_forever())


def _build_embedding_provider(
    settings: AppSettings,
    *,
    factory: type,
) -> object:
    return factory.create(
        settings.embedding_provider,
        model_name=settings.embedding_model,
        device=settings.embedding_device,
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
    )


def _build_llm_provider(settings: AppSettings, *, factory: type) -> object | None:
    if not settings.generation_enabled:
        return None
    return factory.create(
        settings.generation_provider,
        base_url=settings.generation_base_url,
        api_key=settings.generation_api_key,
        default_model=settings.generation_model,
        default_max_tokens=settings.generation_max_tokens,
        default_temperature=settings.generation_temperature,
    )


def _resolve_serve_grpc() -> object:
    legacy_module = sys.modules.get("server.grpc.server")
    if legacy_module is not None and hasattr(legacy_module, "serve_grpc"):
        return legacy_module.serve_grpc

    from project_service.server.grpc.server import serve_grpc

    return serve_grpc


class _NoopServer:
    async def stop(self, grace: int = 0) -> None:
        return None

    async def wait_for_termination(self) -> None:
        return None


if __name__ == "__main__":
    main()
