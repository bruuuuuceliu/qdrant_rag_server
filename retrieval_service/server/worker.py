"""Standalone retrieval HTTP server."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from configs import AppSettings, load_settings
from configs.retrieval.config import RetrievalHttpSettings, load_retrieval_http_settings
from retrieval_service.embedding import EmbeddingProviderFactory
from retrieval_service.health import MetricsCollector
from retrieval_service.placement import PlacementStoreResolver, RetrievalShard, SQLitePlacementRegistry
from retrieval_service.retrieval.factory import ProjectRetrieverFactory
from retrieval_service.retrieval.service import RetrievalService
from retrieval_service.server.app import RetrievalApiServerContext
from retrieval_service.server.app import create_app as create_api_app
from retrieval_service.server.http import RetrievalHttpApp
from retrieval_service.server.http import create_http_app, serve_http
from retrieval_service.services.bm25 import BM25Retriever, QdrantSparseBM25Index
from retrieval_service.services.cache import Tier1MemoryCache, Tier2ResponseCache
from retrieval_service.services.entities import LocalNerExtractor, NoopNerExtractor
from retrieval_service.services.retriever import QdrantVectorRetriever
from retrieval_service.services.sparse_encoder import FastEmbedSparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore
from retrieval_service.storage.filesystem import FilesystemObjectStorage
from retrieval_service.storage.memory import MemoryObjectStorage


ServeHttp = Callable[
    [RetrievalHttpApp, RetrievalHttpSettings],
    Awaitable[asyncio.AbstractServer],
]


@dataclass(slots=True)
class RetrievalHttpServerContext:
    api_app: RetrievalApiServerContext
    http_app: RetrievalHttpApp
    http_server: Any | None
    http_settings: RetrievalHttpSettings
    retrieval_service: Any
    embedding_provider: Any | None
    qdrant_store: Any | None
    bm25_index: Any | None
    sparse_encoder: Any | None
    ner_extractor: Any | None
    tier2_cache: Any | None

    async def shutdown(self) -> None:
        if self.http_server is not None:
            close = getattr(self.http_server, "close", None)
            if close is not None:
                close()
            wait_closed = getattr(self.http_server, "wait_closed", None)
            if wait_closed is not None:
                await wait_closed()
        await self.api_app.shutdown()
        if self.ner_extractor is not None:
            shutdown_ner = getattr(self.ner_extractor, "shutdown", None)
            if shutdown_ner is not None:
                await shutdown_ner()
        if self.bm25_index is not None:
            close_bm25 = getattr(self.bm25_index, "close", None)
            if close_bm25 is not None:
                await close_bm25()
        if self.embedding_provider is not None:
            shutdown_embedding = getattr(self.embedding_provider, "shutdown", None)
            if shutdown_embedding is not None:
                await shutdown_embedding()
        if self.qdrant_store is not None:
            close_qdrant = getattr(self.qdrant_store, "close", None)
            if close_qdrant is not None:
                await close_qdrant()


async def create_worker_server(
    settings: AppSettings | None = None,
    *,
    http_settings: RetrievalHttpSettings | None = None,
    retrieval_service: Any | None = None,
    start_server: bool = True,
    serve_http_fn: Callable[..., Awaitable[Any]] = serve_http,
) -> RetrievalHttpServerContext:
    settings = settings or load_settings()
    http_settings = http_settings or load_retrieval_http_settings(dict(os.environ))
    owned = _OwnedRetrievalDependencies()
    if retrieval_service is None:
        retrieval_service = await _build_retrieval_service(settings, owned=owned)
    api_app = await create_api_app(retrieval_service=retrieval_service)
    http_app = create_http_app(api=api_app)
    http_server = None
    if start_server:
        http_server = await serve_http_fn(app=http_app, settings=http_settings)
    return RetrievalHttpServerContext(
        api_app=api_app,
        http_app=http_app,
        http_server=http_server,
        http_settings=http_settings,
        retrieval_service=retrieval_service,
        embedding_provider=owned.embedding_provider,
        qdrant_store=owned.qdrant_store,
        bm25_index=owned.bm25_index,
        sparse_encoder=owned.sparse_encoder,
        ner_extractor=owned.ner_extractor,
        tier2_cache=owned.tier2_cache,
    )


async def serve_forever(settings: AppSettings | None = None) -> None:
    app = await create_worker_server(settings)
    try:
        if app.http_server is None:
            while True:
                await asyncio.sleep(3600)
        else:
            await app.http_server.serve_forever()
    finally:
        await app.shutdown()


def main() -> None:
    asyncio.run(serve_forever(load_settings()))


@dataclass(slots=True)
class _OwnedRetrievalDependencies:
    embedding_provider: Any | None = None
    qdrant_store: Any | None = None
    bm25_index: Any | None = None
    sparse_encoder: Any | None = None
    ner_extractor: Any | None = None
    tier2_cache: Any | None = None


async def _build_retrieval_service(
    settings: AppSettings,
    *,
    owned: _OwnedRetrievalDependencies,
) -> RetrievalService:
    embedding_provider = EmbeddingProviderFactory.create(
        settings.embedding_provider,
        model_name=settings.embedding_model,
        device=settings.embedding_device,
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
    )
    await embedding_provider.initialize()
    qdrant_store = QdrantStore(
        url=settings.qdrant_url,
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        default_vector_size=settings.embedding_dimension,
    )
    sparse_encoder = FastEmbedSparseTextEncoder(settings.bm25_encoder_model)
    bm25_index = QdrantSparseBM25Index(
        store=qdrant_store,
        sparse_vector_name=settings.bm25_sparse_vector_name,
    )
    await bm25_index.initialize()
    ner_extractor: Any = NoopNerExtractor()
    if settings.ner_provider == "local":
        ner_extractor = LocalNerExtractor(settings.ner_model)
        await ner_extractor.initialize()
    tier2_cache = Tier2ResponseCache(settings.response_cache_db_path)
    await tier2_cache.initialize()
    tier1_cache = Tier1MemoryCache()
    object_storage: Any
    if settings.object_storage_provider == "filesystem":
        object_storage = FilesystemObjectStorage(settings.object_storage_base_path)
    else:
        object_storage = MemoryObjectStorage()

    dense_retriever = QdrantVectorRetriever(qdrant_store)
    bm25_retriever = BM25Retriever(bm25_index)
    retriever_factory = ProjectRetrieverFactory(
        dense_retriever=dense_retriever,
        bm25_retriever=bm25_retriever,
    )
    owned.embedding_provider = embedding_provider
    owned.qdrant_store = qdrant_store
    owned.bm25_index = bm25_index
    owned.sparse_encoder = sparse_encoder
    owned.ner_extractor = ner_extractor
    owned.tier2_cache = tier2_cache
    return RetrievalService(
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
        retriever_factory=retriever_factory,
        sparse_encoder=sparse_encoder,
        ner_extractor=ner_extractor,
        tier1_cache=tier1_cache,
        tier2_cache=tier2_cache,
        object_storage=object_storage,
        bm25_index=bm25_index,
        metrics=MetricsCollector(),
        placement_store_resolver=_build_placement_store_resolver(
            settings,
            qdrant_store=qdrant_store,
        ),
    )


def _build_placement_store_resolver(
    settings: AppSettings,
    *,
    qdrant_store: Any,
) -> PlacementStoreResolver:
    if not settings.retrieval_placement_enabled:
        return PlacementStoreResolver(default_store=qdrant_store)
    registry = SQLitePlacementRegistry(settings.retrieval_placement_db_path)
    registry.initialize()
    endpoint = settings.qdrant_url or f"http://{settings.qdrant_host}:{settings.qdrant_port}"
    registry.upsert(
        RetrievalShard(
            shard_id=settings.retrieval_placement_shard_id,
            cluster_id=settings.retrieval_placement_cluster_id,
            qdrant_endpoint=endpoint,
        )
    )
    return PlacementStoreResolver(
        default_store=qdrant_store,
        shard_repository=registry,
        default_vector_size=settings.embedding_dimension,
    )


if __name__ == "__main__":
    main()
