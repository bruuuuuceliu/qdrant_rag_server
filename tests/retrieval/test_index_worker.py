"""Retrieval indexing worker startup tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from configs.config import AppSettings
from configs.retrieval.config import RetrievalIndexWorkerSettings
from retrieval_service.indexing.worker import (
    _build_placement_store_resolver,
    _build_queue,
    create_queue_worker_server,
    create_worker_server,
)
from shared.contracts import TOPICS
from shared.queue import LocalQueueBroker, QueueMessage, SQLiteQueueBroker


class RetrievalIndexWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_worker_server_starts_consumer_with_injected_dependencies(self) -> None:
        queue = LocalQueueBroker()
        indexing_service = _FakeIndexingService()
        embedding_provider = _Closable()
        qdrant_store = _Closable(close_method="close")
        bm25_index = _Closable(close_method="close")
        settings = RetrievalIndexWorkerSettings(
            request_topic="index.custom",
            queue_broker="local",
        )

        app = await create_queue_worker_server(
            _settings(),
            worker_settings=settings,
            queue=queue,
            indexing_service=indexing_service,
            embedding_provider=embedding_provider,
            qdrant_store=qdrant_store,
            sparse_encoder=object(),
            bm25_index=bm25_index,
            ner_extractor=None,
        )

        await queue.publish(
            QueueMessage(
                topic="index.custom",
                key="req1",
                payload={
                    "request_id": "req1",
                    "response_topic": "index.responses.req1",
                    "job_id": "job1",
                    "collection_name": "rag_p1_v1",
                    "chunks": [{"chunk_id": "c1", "chunk_index": 0, "text": "hello"}],
                    "payloads": [],
                    "retrieval_config": {},
                },
            )
        )

        response = await asyncio.wait_for(queue.consume("index.responses.req1"), timeout=1)
        queue.task_done("index.responses.req1")

        self.assertTrue(app.index_app.enabled)
        self.assertEqual(app.index_app.topic, "index.custom")
        self.assertEqual(indexing_service.request.collection_name, "rag_p1_v1")
        self.assertTrue(response.payload["ok"])

        await app.shutdown()
        self.assertTrue(embedding_provider.closed)
        self.assertTrue(qdrant_store.closed)
        self.assertTrue(bm25_index.closed)

    async def test_disabled_worker_does_not_start_consumer(self) -> None:
        app = await create_queue_worker_server(
            _settings(),
            worker_settings=RetrievalIndexWorkerSettings(enabled=False),
            queue=LocalQueueBroker(),
            indexing_service=_FakeIndexingService(),
            embedding_provider=_Closable(),
            qdrant_store=_Closable(close_method="close"),
            bm25_index=None,
            sparse_encoder=None,
            ner_extractor=None,
        )

        self.assertFalse(app.index_app.enabled)
        self.assertIsNone(app.index_app.consumer)
        await app.shutdown()

    async def test_create_worker_server_wires_broker_helper(self) -> None:
        indexing_service = _FakeIndexingService()
        embedding_provider = _Closable()
        qdrant_store = _Closable(close_method="close")
        bm25_index = _Closable(close_method="close")
        settings = RetrievalIndexWorkerSettings(
            service_name="retrieval-index-a",
            command_topic="retrieval.index.commands",
        )

        app = await create_worker_server(
            _settings(),
            worker_settings=settings,
            indexing_service=indexing_service,
            embedding_provider=embedding_provider,
            qdrant_store=qdrant_store,
            sparse_encoder=object(),
            bm25_index=bm25_index,
            ner_extractor=None,
        )

        self.assertEqual(app.settings.command_topic, "retrieval.index.commands")
        self.assertEqual(app.helper_app.command_topic, "retrieval.index.commands")
        self.assertIs(app.helper_app.handler._indexing_service, indexing_service)
        health = await app.health()
        self.assertTrue(health.ready)
        self.assertEqual(health.details["command_topic"], "retrieval.index.commands")

        await app.shutdown()
        self.assertTrue(embedding_provider.closed)
        self.assertTrue(qdrant_store.closed)
        self.assertTrue(bm25_index.closed)

    def test_index_worker_settings_use_broker_helper_topic(self) -> None:
        self.assertEqual(
            RetrievalIndexWorkerSettings().command_topic,
            TOPICS.helper_retrieval_index_commands,
        )


class RetrievalIndexWorkerQueueTest(unittest.TestCase):
    def test_build_queue_supports_local(self) -> None:
        queue = _build_queue(RetrievalIndexWorkerSettings(queue_broker="local"))

        self.assertIsInstance(queue, LocalQueueBroker)

    def test_build_queue_supports_sqlite(self) -> None:
        queue = _build_queue(
            RetrievalIndexWorkerSettings(
                queue_broker="sqlite",
                queue_db_path=Path(":memory:"),
            )
        )

        self.assertIsInstance(queue, SQLiteQueueBroker)

    def test_build_queue_rejects_unknown_broker(self) -> None:
        with self.assertRaisesRegex(ValueError, "RETRIEVAL_INDEX_QUEUE_BROKER"):
            _build_queue(RetrievalIndexWorkerSettings(queue_broker="bad"))

    def test_build_placement_store_resolver_uses_registry(self) -> None:
        with TemporaryDirectory() as tempdir:
            settings = _settings()
            settings = _settings_with_placement_db(settings, Path(tempdir) / "placement.db")
            resolver = _build_placement_store_resolver(
                settings,
                qdrant_store=object(),
            )

        self.assertIsNotNone(resolver)

class _FakeIndexingService:
    request = None

    async def index_chunks(self, request):
        self.request = request
        return SimpleNamespace(
            chunk_count=len(request.chunks),
            dense_enabled=True,
            sparse_enabled=False,
        )


class _Closable:
    def __init__(self, *, close_method: str = "shutdown") -> None:
        self.closed = False
        self.close_method = close_method

    async def shutdown(self) -> None:
        if self.close_method == "shutdown":
            self.closed = True

    async def close(self) -> None:
        if self.close_method == "close":
            self.closed = True


def _settings() -> AppSettings:
    return AppSettings(
        config_db_path=Path(":memory:"),
        response_cache_db_path=Path(":memory:"),
        grpc_port=50051,
        qdrant_url=None,
        qdrant_host="localhost",
        qdrant_port=6333,
        max_per_project=20,
        max_per_user=5,
        ingest_worker_count=1,
        embedding_provider="local",
        embedding_model="fake-model",
        embedding_device="cpu",
        embedding_api_key="",
        embedding_base_url="",
        embedding_dimension=3,
        generation_enabled=False,
        bm25_encoder_model="fake-bm25",
    )


def _settings_with_placement_db(settings: AppSettings, db_path: Path) -> AppSettings:
    return replace(settings, retrieval_placement_db_path=db_path)


if __name__ == "__main__":
    unittest.main()
