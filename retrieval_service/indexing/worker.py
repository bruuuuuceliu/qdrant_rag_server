"""Standalone retrieval indexing worker server."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from broker_service import BrokerSettings
from configs import AppSettings, load_settings
from configs.retrieval.config import (
    RetrievalIndexWorkerSettings,
    load_retrieval_index_worker_settings,
)
from retrieval_service.embedding import EmbeddingProviderFactory
from retrieval_service.indexing.app import RetrievalIndexAppContext
from retrieval_service.indexing.app import create_app as create_index_app
from retrieval_service.indexing.helper_app import (
    RetrievalIndexHelperServerContext,
    create_helper_app,
)
from retrieval_service.indexing.service import IndexingService
from retrieval_service.placement import (
    PlacementStoreResolver,
    RetrievalShard,
    SQLitePlacementRegistry,
)
from retrieval_service.services.bm25 import QdrantSparseBM25Index
from retrieval_service.services.entities import LocalNerExtractor, NoopNerExtractor
from retrieval_service.services.sparse_encoder import FastEmbedSparseTextEncoder
from retrieval_service.services.vector_store import QdrantStore
from shared.runtime_health import RuntimeHealth
from shared.queue import LocalQueueBroker, QueueBroker, SQLiteQueueBroker


@dataclass(slots=True)
class RetrievalIndexWorkerServerContext:
    helper_app: RetrievalIndexHelperServerContext
    indexing_service: IndexingService
    settings: RetrievalIndexWorkerSettings
    embedding_provider: Any
    qdrant_store: Any
    bm25_index: Any | None
    sparse_encoder: Any | None
    ner_extractor: Any | None

    async def shutdown(self) -> None:
        await self.helper_app.stop()
        if self.ner_extractor is not None:
            shutdown_ner = getattr(self.ner_extractor, "shutdown", None)
            if shutdown_ner is not None:
                await shutdown_ner()
        if self.bm25_index is not None:
            close_bm25 = getattr(self.bm25_index, "close", None)
            if close_bm25 is not None:
                await close_bm25()
        shutdown_embedding = getattr(self.embedding_provider, "shutdown", None)
        if shutdown_embedding is not None:
            await shutdown_embedding()
        close_qdrant = getattr(self.qdrant_store, "close", None)
        if close_qdrant is not None:
            await close_qdrant()

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            service=self.settings.service_name,
            ready=True,
            dependencies={
                "indexing_service": self.indexing_service is not None,
                "broker_helper": self.helper_app is not None,
            },
            details={"command_topic": self.settings.command_topic},
        )


@dataclass(slots=True)
class RetrievalIndexQueueWorkerServerContext:
    index_app: RetrievalIndexAppContext
    queue: QueueBroker
    indexing_service: IndexingService
    settings: RetrievalIndexWorkerSettings
    embedding_provider: Any
    qdrant_store: Any
    bm25_index: Any | None
    sparse_encoder: Any | None
    ner_extractor: Any | None

    async def shutdown(self) -> None:
        await self.index_app.shutdown()
        if self.ner_extractor is not None:
            shutdown_ner = getattr(self.ner_extractor, "shutdown", None)
            if shutdown_ner is not None:
                await shutdown_ner()
        if self.bm25_index is not None:
            close_bm25 = getattr(self.bm25_index, "close", None)
            if close_bm25 is not None:
                await close_bm25()
        shutdown_embedding = getattr(self.embedding_provider, "shutdown", None)
        if shutdown_embedding is not None:
            await shutdown_embedding()
        close_qdrant = getattr(self.qdrant_store, "close", None)
        if close_qdrant is not None:
            await close_qdrant()


async def create_worker_server(
    settings: AppSettings | None = None,
    *,
    worker_settings: RetrievalIndexWorkerSettings | None = None,
    broker_settings: BrokerSettings | None = None,
    indexing_service: IndexingService | None = None,
    embedding_provider: Any | None = None,
    qdrant_store: Any | None = None,
    sparse_encoder: Any | None = None,
    bm25_index: Any | None = None,
    ner_extractor: Any | None = None,
) -> RetrievalIndexWorkerServerContext:
    settings = settings or load_settings()
    worker_settings = worker_settings or load_retrieval_index_worker_settings(
        dict(os.environ)
    )

    if embedding_provider is None:
        embedding_provider = EmbeddingProviderFactory.create(
            settings.embedding_provider,
            model_name=settings.embedding_model,
            device=settings.embedding_device,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
        )
        await embedding_provider.initialize()

    if qdrant_store is None:
        qdrant_store = QdrantStore(
            url=settings.qdrant_url,
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            default_vector_size=settings.embedding_dimension,
        )

    if sparse_encoder is None:
        sparse_encoder = FastEmbedSparseTextEncoder(settings.bm25_encoder_model)
    if bm25_index is None:
        bm25_index = QdrantSparseBM25Index(
            store=qdrant_store,
            sparse_vector_name=settings.bm25_sparse_vector_name,
        )
        await bm25_index.initialize()
    if ner_extractor is None:
        ner_extractor = NoopNerExtractor()
        if settings.ner_provider == "local":
            ner_extractor = LocalNerExtractor(settings.ner_model)
            await ner_extractor.initialize()

    if indexing_service is None:
        indexing_service = IndexingService(
            embedding_provider=embedding_provider,
            qdrant_store=qdrant_store,
            sparse_encoder=sparse_encoder,
            ner_extractor=ner_extractor,
            placement_store_resolver=_build_placement_store_resolver(
                settings,
                qdrant_store=qdrant_store,
            ),
        )

    helper_app = create_helper_app(
        indexing_service=indexing_service,
        broker_settings=broker_settings,
        service_name=worker_settings.service_name,
        command_topic=worker_settings.command_topic,
    )
    return RetrievalIndexWorkerServerContext(
        helper_app=helper_app,
        indexing_service=indexing_service,
        settings=worker_settings,
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
        bm25_index=bm25_index,
        sparse_encoder=sparse_encoder,
        ner_extractor=ner_extractor,
    )


async def create_queue_worker_server(
    settings: AppSettings | None = None,
    *,
    worker_settings: RetrievalIndexWorkerSettings | None = None,
    queue: QueueBroker | None = None,
    indexing_service: IndexingService | None = None,
    embedding_provider: Any | None = None,
    qdrant_store: Any | None = None,
    sparse_encoder: Any | None = None,
    bm25_index: Any | None = None,
    ner_extractor: Any | None = None,
) -> RetrievalIndexQueueWorkerServerContext:
    settings = settings or load_settings()
    worker_settings = worker_settings or load_retrieval_index_worker_settings(
        dict(os.environ)
    )
    queue = queue or _build_queue(worker_settings)

    helper_context = await create_worker_server(
        settings,
        worker_settings=worker_settings,
        indexing_service=indexing_service,
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
        sparse_encoder=sparse_encoder,
        bm25_index=bm25_index,
        ner_extractor=ner_extractor,
    )
    index_app = await create_index_app(
        queue=queue,
        indexing_service=helper_context.indexing_service,
        enabled=worker_settings.enabled,
        topic=worker_settings.request_topic,
    )
    return RetrievalIndexQueueWorkerServerContext(
        index_app=index_app,
        queue=queue,
        indexing_service=helper_context.indexing_service,
        settings=helper_context.settings,
        embedding_provider=helper_context.embedding_provider,
        qdrant_store=helper_context.qdrant_store,
        bm25_index=helper_context.bm25_index,
        sparse_encoder=helper_context.sparse_encoder,
        ner_extractor=helper_context.ner_extractor,
    )


async def serve_forever(settings: AppSettings | None = None) -> None:
    app = await create_worker_server(settings)
    app.helper_app.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.shutdown()


def main() -> None:
    asyncio.run(serve_forever(load_settings()))


def _build_queue(settings: RetrievalIndexWorkerSettings) -> QueueBroker:
    broker = settings.queue_broker.strip().lower()
    if broker == "local":
        return LocalQueueBroker(maxsize=settings.queue_maxsize)
    if broker == "sqlite":
        return SQLiteQueueBroker(settings.queue_db_path, maxsize=settings.queue_maxsize)
    raise ValueError("RETRIEVAL_INDEX_QUEUE_BROKER must be one of: sqlite, local")


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
