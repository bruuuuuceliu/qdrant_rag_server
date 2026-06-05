"""Local application bootstrap for the RAG gRPC server."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppSettings:
    config_db_path: Path
    response_cache_db_path: Path
    grpc_port: int
    qdrant_url: str | None
    qdrant_host: str
    qdrant_port: int
    max_per_project: int
    max_per_user: int
    ingest_worker_count: int
    embedding_provider: str
    embedding_model: str
    embedding_device: str
    embedding_api_key: str
    embedding_base_url: str
    embedding_dimension: int
    generation_enabled: bool

    @classmethod
    def from_env(cls) -> AppSettings:
        return cls(
            config_db_path=Path(_env("RAG_CONFIG_DB_PATH", "/var/lib/rag/config.db")),
            response_cache_db_path=Path(
                _env("RAG_RESPONSE_CACHE_DB_PATH", "/var/lib/rag/response_cache.db")
            ),
            grpc_port=_env_int("RAG_GRPC_PORT", 50051),
            qdrant_url=os.getenv("RAG_QDRANT_URL") or None,
            qdrant_host=_env("RAG_QDRANT_HOST", "localhost"),
            qdrant_port=_env_int("RAG_QDRANT_PORT", 6333),
            max_per_project=_env_int("RAG_MAX_PER_PROJECT", 20),
            max_per_user=_env_int("RAG_MAX_PER_USER", 5),
            ingest_worker_count=_env_int("RAG_INGEST_WORKERS", 4),
            embedding_provider=_env("RAG_EMBEDDING_PROVIDER", "local"),
            embedding_model=_env("RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"),
            embedding_device=_env("RAG_EMBEDDING_DEVICE", "cpu"),
            embedding_api_key=_env("RAG_EMBEDDING_API_KEY", ""),
            embedding_base_url=_env(
                "RAG_EMBEDDING_BASE_URL",
                "https://openrouter.ai/api/v1/embeddings",
            ),
            embedding_dimension=_env_int("RAG_EMBEDDING_DIMENSION", 768),
            generation_enabled=_env_bool("RAG_GENERATION_ENABLED", False),
        )


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
        await self.embedding_provider.shutdown()
        await self.qdrant_store.close()


async def create_app(settings: AppSettings | None = None) -> AppContext:
    settings = settings or AppSettings.from_env()

    from rag_server.adapters import (
        ProjectAdapterRegistry,
        ProjectAdapterResolver,
        WebsiteProjectAdapter,
    )
    from rag_server.config import SQLiteProjectConfigRepository
    from rag_server.engine.engine import RagEngine
    from rag_server.gateway import AsyncConcurrencyLimiter, RagGateway
    from rag_server.grpc.server import serve_grpc
    from rag_server.health import HealthChecker, MetricsCollector
    from rag_server.services.cache import Tier1MemoryCache, Tier2ResponseCache
    from rag_server.services.embedding import EmbeddingService, RemoteEmbeddingService
    from rag_server.services.generation import OpenRouterClient
    from rag_server.services.vector_store import QdrantStore

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
        local_cls=EmbeddingService,
        remote_cls=RemoteEmbeddingService,
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
    openrouter_client = OpenRouterClient() if settings.generation_enabled else None

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


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _build_embedding_provider(
    settings: AppSettings,
    *,
    local_cls: type,
    remote_cls: type,
) -> object:
    provider = settings.embedding_provider.strip().lower()
    if provider == "local":
        return local_cls(
            model_name=settings.embedding_model,
            device=settings.embedding_device,
        )
    if provider in {"openrouter", "remote"}:
        return remote_cls(
            api_key=settings.embedding_api_key,
            model_name=settings.embedding_model,
            base_url=settings.embedding_base_url,
        )
    raise ValueError(
        "RAG_EMBEDDING_PROVIDER must be one of: local, openrouter, remote"
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


if __name__ == "__main__":
    main()
