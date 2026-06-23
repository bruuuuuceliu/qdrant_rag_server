"""Retrieval indexing worker startup tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import subprocess
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from configs.config import AppSettings
from configs.retrieval.config import RetrievalIndexWorkerSettings
from retrieval_service.indexing.worker import (
    _build_placement_store_resolver,
    _build_queue,
    create_worker_server,
)
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

        app = await create_worker_server(
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
        app = await create_worker_server(
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

    def test_local_runner_references_retrieval_index_worker(self) -> None:
        root = Path(__file__).resolve().parents[1]
        run_all = (root / "examples/local/run-all.sh").read_text()
        stop_all = (root / "examples/local/stop-all.sh").read_text()
        readme = (root / "examples/local/README.md").read_text()

        self.assertIn("retrieval_service.indexing.worker", run_all)
        self.assertIn("PYTHON_BIN", run_all)
        self.assertIn("export INGESTION_RETRIEVAL_INDEX_ENABLED=true", run_all)
        self.assertIn(
            "export INGESTION_RETRIEVAL_INDEX_QUEUE_DB_PATH=\"${RETRIEVAL_INDEX_QUEUE_DB_PATH}\"",
            run_all,
        )
        self.assertIn(
            "export INGESTION_RETRIEVAL_INDEX_TOPIC=\"${RETRIEVAL_INDEX_REQUEST_TOPIC}\"",
            run_all,
        )
        self.assertIn("INGESTION_RETRIEVAL_INDEX_RESPONSE_TIMEOUT", run_all)
        self.assertIn("RETRIEVAL_INDEX_QUEUE_DB_PATH", run_all)
        self.assertIn("retrieval-index-worker.pid", stop_all)
        self.assertIn("retrieval-index-worker.log", readme)
        self.assertIn("waits for the index response", readme)

    def test_local_runner_split_no_server_reports_index_publication(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as tempdir:
            runtime_dir = Path(tempdir) / "run"
            data_dir = Path(tempdir) / "data"
            result = subprocess.run(
                [
                    str(root / "examples" / "local" / "run-all.sh"),
                    "--split-services",
                    "--no-server",
                    "--project-id",
                    "smoke",
                    "--project-type",
                    "website",
                ],
                cwd=root,
                env={
                    "PATH": "/usr/bin:/bin",
                    "RAG_LOCAL_RUNTIME_DIR": str(runtime_dir),
                    "RAG_LOCAL_DATA_DIR": str(data_dir),
                    "RAG_EMBEDDING_PROVIDER": "local",
                },
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertIn("ingestion_mode:      external", result.stdout)
        self.assertIn("queue_broker:        sqlite", result.stdout)
        self.assertIn("ingestion_index_pub: true", result.stdout)
        self.assertIn("project_client_mode: grpc", result.stdout)


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
