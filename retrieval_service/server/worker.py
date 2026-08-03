"""Standalone retrieval broker-helper server."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from broker_service import BrokerSettings
from configs import AppSettings, load_settings
from configs.retrieval.config import (
    RetrievalHelperSettings,
    load_retrieval_helper_settings,
)
from retrieval_service.embedding import EmbeddingProviderFactory
from retrieval_service.health import MetricsCollector
from retrieval_service.placement import PlacementStoreResolver, RetrievalShard, SQLitePlacementRegistry
from retrieval_service.retrieval.factory import ProjectRetrieverFactory
from retrieval_service.retrieval.handler import RetrievalApiHandler
from retrieval_service.retrieval.app import create_app as create_retrieval_app
from retrieval_service.retrieval.service import RetrievalService
from retrieval_service.server.helper_app import RetrievalHelperServerContext, create_helper_app
from retrieval_service.services.bm25 import BM25Retriever, QdrantSparseBM25Index
from retrieval_service.services.cache import Tier1MemoryCache, Tier2ResponseCache
from retrieval_service.services.entities import LocalNerExtractor, NoopNerExtractor
from retrieval_service.services.retriever import QdrantVectorRetriever
from retrieval_service.services.sparse_encoder import FastEmbedSparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore
from retrieval_service.storage.filesystem import FilesystemObjectStorage
from retrieval_service.storage.memory import MemoryObjectStorage
from shared.logging import configure_logging
from shared.runtime_health import RuntimeHealth


@dataclass(slots=True)
class RetrievalHelperApiContext:
    """Broker-helper API context backed by a retrieval app."""

    app: Any
    handler: RetrievalApiHandler

    async def search(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self.handler.handle_search(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def delete_document(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self.handler.handle_delete_document(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def handle_memory_search(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self.handler.handle_memory_search(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def get_raw_document(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        return await self.handler.handle_raw_document(
            payload,
            fallback_request_id=fallback_request_id,
        )

    async def shutdown(self) -> None:
        await self.app.shutdown()


@dataclass(slots=True)
class RetrievalWorkerServerContext:
    api_app: RetrievalHelperApiContext
    helper_app: RetrievalHelperServerContext
    helper_settings: RetrievalHelperSettings
    retrieval_service: Any
    owned: "OwnedRetrievalDependencies"

    async def shutdown(self) -> None:
        await self.helper_app.stop()
        await _shutdown_owned(self.owned, self.api_app)

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            service=self.helper_settings.service_name,
            ready=True,
            dependencies={
                "retrieval_service": self.retrieval_service is not None,
                "broker_helper": self.helper_app is not None,
            },
            details={"command_topic": self.helper_settings.command_topic},
        )


async def create_worker_server(
    settings: AppSettings | None = None,
    *,
    helper_settings: RetrievalHelperSettings | None = None,
    retrieval_service: Any | None = None,
    broker_settings: BrokerSettings | None = None,
) -> RetrievalWorkerServerContext:
    settings = settings or load_settings()
    helper_settings = helper_settings or load_retrieval_helper_settings(dict(os.environ))
    owned = OwnedRetrievalDependencies()
    if retrieval_service is None:
        retrieval_service = await _build_retrieval_service(settings, owned=owned)
    app = await create_retrieval_app(retrieval_service=retrieval_service)
    api_app = RetrievalHelperApiContext(
        app=app,
        handler=RetrievalApiHandler(app=app),
    )
    helper_app = create_helper_app(
        api=api_app,
        broker_settings=broker_settings,
        service_name=helper_settings.service_name,
        command_topic=helper_settings.command_topic,
    )
    return RetrievalWorkerServerContext(
        api_app=api_app,
        helper_app=helper_app,
        helper_settings=helper_settings,
        retrieval_service=retrieval_service,
        owned=owned,
    )


async def serve_forever(settings: AppSettings | None = None) -> None:
    app = await create_worker_server(settings)
    await app.helper_app.start_runtime()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.shutdown()


def main() -> None:
    configure_logging()
    asyncio.run(serve_forever(load_settings()))


@dataclass(slots=True)
class OwnedRetrievalDependencies:
    embedding_provider: Any | None = None
    qdrant_store: Any | None = None
    bm25_index: Any | None = None
    sparse_encoder: Any | None = None
    ner_extractor: Any | None = None
    tier2_cache: Any | None = None


async def _build_retrieval_service(
    settings: AppSettings,
    *,
    owned: OwnedRetrievalDependencies,
) -> RetrievalService:
    embedding_provider = EmbeddingProviderFactory.create(
        settings.embedding_provider,
        model_name=settings.embedding_model,
        device=settings.embedding_device,
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        dimension=settings.embedding_dimension,
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


async def _shutdown_owned(
    owned: OwnedRetrievalDependencies,
    api_app: RetrievalHelperApiContext,
) -> None:
    await api_app.shutdown()
    if owned.ner_extractor is not None:
        shutdown_ner = getattr(owned.ner_extractor, "shutdown", None)
        if shutdown_ner is not None:
            await shutdown_ner()
    if owned.bm25_index is not None:
        close_bm25 = getattr(owned.bm25_index, "close", None)
        if close_bm25 is not None:
            await close_bm25()
    if owned.embedding_provider is not None:
        shutdown_embedding = getattr(owned.embedding_provider, "shutdown", None)
        if shutdown_embedding is not None:
            await shutdown_embedding()
    if owned.qdrant_store is not None:
        close_qdrant = getattr(owned.qdrant_store, "close", None)
        if close_qdrant is not None:
            await close_qdrant()


if __name__ == "__main__":
    main()
