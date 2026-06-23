"""Standalone ingestion worker server tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from configs.ingestion import IngestionSettings
from ingestion_service.service import IngestionService
from ingestion_service.server.worker import _build_retrieval_queue, create_worker_server
from shared.queue import LocalQueueBroker, SQLiteQueueBroker


class IngestionWorkerServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_worker_server_uses_sqlite_queue_and_retrieval_index_queue(self) -> None:
        with TemporaryDirectory() as tempdir:
            ingestion_app = MagicMock()
            ingestion_app.shutdown = AsyncMock()
            settings = IngestionSettings(
                request_topic="custom.ingest",
                queue_maxsize=5,
                job_db_path=Path(tempdir) / "jobs.db",
            )

            with patch(
                "ingestion_service.server.worker.create_ingestion_app",
                AsyncMock(return_value=ingestion_app),
            ) as create_ingestion_app, patch.dict(
                "os.environ",
                {
                    "INGESTION_QUEUE_BROKER": "sqlite",
                    "INGESTION_QUEUE_DB_PATH": str(Path(tempdir) / "queue.db"),
                },
            ):
                context = await create_worker_server(
                    MagicMock(),
                    ingestion_settings=settings,
                    retrieval_queue=MagicMock(),
                )

            create_ingestion_app.assert_awaited_once()
            self.assertIsNotNone(create_ingestion_app.await_args.kwargs["jobs"])
            self.assertIsInstance(
                create_ingestion_app.await_args.kwargs["ingestion_service"],
                IngestionService,
            )
            self.assertIsNotNone(create_ingestion_app.await_args.kwargs["retrieval_queue"])
            self.assertEqual(
                create_ingestion_app.await_args.kwargs["retrieval_index_topic"],
                "retrieval.index.requests",
            )
            self.assertEqual(
                create_ingestion_app.await_args.kwargs[
                    "retrieval_index_response_timeout"
                ],
                30.0,
            )
            self.assertEqual(create_ingestion_app.await_args.kwargs["topic"], "custom.ingest")
            self.assertIsInstance(context.queue, SQLiteQueueBroker)

            await context.shutdown()
            ingestion_app.shutdown.assert_awaited_once()

    async def test_create_worker_server_builds_retrieval_index_queue_when_enabled(self) -> None:
        with TemporaryDirectory() as tempdir:
            ingestion_app = MagicMock()
            ingestion_app.shutdown = AsyncMock()
            settings = IngestionSettings(
                request_topic="custom.ingest",
                queue_maxsize=5,
                job_db_path=Path(tempdir) / "jobs.db",
                retrieval_index_enabled=True,
                retrieval_index_topic="custom.index",
                retrieval_index_queue_broker="sqlite",
                retrieval_index_queue_db_path=Path(tempdir) / "queue.db",
                retrieval_index_queue_maxsize=7,
                retrieval_index_response_timeout=1.5,
            )

            with patch(
                "ingestion_service.server.worker.create_ingestion_app",
                AsyncMock(return_value=ingestion_app),
            ) as create_ingestion_app, patch.dict(
                "os.environ",
                {
                    "INGESTION_QUEUE_BROKER": "sqlite",
                    "INGESTION_QUEUE_DB_PATH": str(Path(tempdir) / "ingest_queue.db"),
                },
            ):
                context = await create_worker_server(
                    MagicMock(),
                    ingestion_settings=settings,
                )

            retrieval_queue = create_ingestion_app.await_args.kwargs["retrieval_queue"]
            self.assertIsInstance(retrieval_queue, SQLiteQueueBroker)
            self.assertEqual(
                create_ingestion_app.await_args.kwargs["retrieval_index_topic"],
                "custom.index",
            )
            self.assertEqual(
                create_ingestion_app.await_args.kwargs[
                    "retrieval_index_response_timeout"
                ],
                1.5,
            )

            await context.shutdown()

    async def test_create_worker_server_rejects_disabled_retrieval_index_queue(self) -> None:
        with TemporaryDirectory() as tempdir:
            settings = IngestionSettings(
                job_db_path=Path(tempdir) / "jobs.db",
                retrieval_index_enabled=False,
            )

            with patch.dict(
                "os.environ",
                {
                    "INGESTION_QUEUE_BROKER": "sqlite",
                    "INGESTION_QUEUE_DB_PATH": str(Path(tempdir) / "ingest_queue.db"),
                },
            ):
                with self.assertRaisesRegex(ValueError, "INGESTION_RETRIEVAL_INDEX_ENABLED"):
                    await create_worker_server(
                        MagicMock(),
                        ingestion_settings=settings,
                    )

    def test_build_retrieval_queue_supports_local(self) -> None:
        queue = _build_retrieval_queue(
            IngestionSettings(
                retrieval_index_queue_broker="local",
                retrieval_index_queue_maxsize=3,
            )
        )

        self.assertIsInstance(queue, LocalQueueBroker)

    def test_build_retrieval_queue_rejects_unknown_broker(self) -> None:
        with self.assertRaisesRegex(ValueError, "INGESTION_RETRIEVAL_INDEX_QUEUE_BROKER"):
            _build_retrieval_queue(
                IngestionSettings(retrieval_index_queue_broker="bad")
            )

if __name__ == "__main__":
    unittest.main()
