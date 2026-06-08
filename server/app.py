"""Local application bootstrap for the retrieval gRPC server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from configs import AppSettings, load_settings


@dataclass(slots=True)
class AppContext:
    settings: AppSettings
    config_repo: object
    gateway: object
    engine: object
    embedding_provider: object
    qdrant_store: object
    metrics: object
    health_checker: object
    openrouter_client: object | None
    server: object

    async def shutdown(self) -> None:
        await self.server.stop(grace=5)
        await self.engine.shutdown()
        if self.openrouter_client is not None:
            await self.openrouter_client.shutdown()
        await self.embedding_provider.shutdown()
        await self.qdrant_store.close()


async def create_app(settings: AppSettings | None = None) -> AppContext:
    settings = settings or load_settings()

    from retrieval_service.adapters import (
        ProjectAdapterRegistry,
        ProjectAdapterResolver,
        WebsiteProjectAdapter,
    )
    from configs import SQLiteProjectConfigRepository
    from retrieval_service.engine.engine import RagEngine
    from retrieval_service.gateway import AsyncConcurrencyLimiter, RagGateway
    from retrieval_service.health import HealthChecker, MetricsCollector
    from retrieval_service.services.cache import Tier1MemoryCache, Tier2ResponseCache
    from retrieval_service.services.embedding import EmbeddingProviderFactory
    from retrieval_service.services.generation import LLMProviderFactory
    from retrieval_service.services.vector_store import QdrantStore
    from server.grpc.server import serve_grpc

    config_repo = SQLiteProjectConfigRepository(settings.config_db_path)
    await config_repo.initialize()

    registry = ProjectAdapterRegistry()
    registry.register(WebsiteProjectAdapter())
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
    openrouter_client = _build_llm_provider(settings, factory=LLMProviderFactory)
    if openrouter_client is not None:
        await openrouter_client.initialize()

    engine = RagEngine(
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
        tier1_cache=tier1_cache,
        tier2_cache=tier2_cache,
        openrouter_client=openrouter_client,
        metrics=metrics,
        ingest_worker_count=settings.ingest_worker_count,
    )
    health_checker = HealthChecker(
        qdrant_store=qdrant_store,
        embed_fn=embedding_provider,
        tier1_cache=tier1_cache,
        tier2_cache=tier2_cache,
        config_repo=config_repo,
        openrouter_client=openrouter_client,
    )
    server = await serve_grpc(
        gateway=gateway,
        engine=engine,
        health_checker=health_checker,
        port=settings.grpc_port,
    )
    return AppContext(
        settings=settings,
        config_repo=config_repo,
        gateway=gateway,
        engine=engine,
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
        metrics=metrics,
        health_checker=health_checker,
        openrouter_client=openrouter_client,
        server=server,
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


if __name__ == "__main__":
    main()
