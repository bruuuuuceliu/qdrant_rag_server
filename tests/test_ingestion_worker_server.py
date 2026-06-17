"""Standalone ingestion worker server tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from configs.ingestion import IngestionSettings
from ingestion_service.service import IngestionService
from ingestion_service.server.worker import create_worker_server
from shared.queue import SQLiteQueueBroker


class IngestionWorkerServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_worker_server_uses_sqlite_queue_and_project_client(self) -> None:
        with TemporaryDirectory() as tempdir:
            project_app = MagicMock()
            project_app.project_client = MagicMock()
            project_app.shutdown = AsyncMock()
            ingestion_app = MagicMock()
            ingestion_app.shutdown = AsyncMock()
            settings = IngestionSettings(
                request_topic="custom.ingest",
                queue_maxsize=5,
                job_db_path=Path(tempdir) / "jobs.db",
            )

            with patch(
                "ingestion_service.server.worker.create_project_app",
                AsyncMock(return_value=project_app),
            ) as create_project_app, patch(
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

            create_project_app.assert_awaited_once()
            self.assertFalse(create_project_app.await_args.kwargs["start_server"])
            create_ingestion_app.assert_awaited_once()
            self.assertIs(create_ingestion_app.await_args.kwargs["project_documents"], project_app.project_client)
            self.assertIsNotNone(create_ingestion_app.await_args.kwargs["jobs"])
            self.assertIsInstance(
                create_ingestion_app.await_args.kwargs["ingestion_service"],
                IngestionService,
            )
            self.assertIsNotNone(create_ingestion_app.await_args.kwargs["retrieval_queue"])
            self.assertEqual(create_ingestion_app.await_args.kwargs["topic"], "custom.ingest")
            self.assertIsInstance(context.queue, SQLiteQueueBroker)

            await context.shutdown()
            ingestion_app.shutdown.assert_awaited_once()
            project_app.shutdown.assert_awaited_once()

    async def test_create_worker_server_grpc_project_mode_uses_remote_client(self) -> None:
        with TemporaryDirectory() as tempdir:
            remote_client = _FakeRemoteProjectClient()
            ingestion_app = MagicMock()
            ingestion_app.shutdown = AsyncMock()
            settings = IngestionSettings(
                request_topic="custom.ingest",
                queue_maxsize=5,
                job_db_path=Path(tempdir) / "jobs.db",
                project_client_mode="grpc",
                project_grpc_target="localhost:50052",
            )

            with patch(
                "ingestion_service.server.worker.create_project_app",
                AsyncMock(),
            ) as create_project_app, patch(
                "ingestion_service.server.worker.RemoteProjectServiceClient",
                return_value=remote_client,
            ) as remote_client_class, patch(
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
                )

            create_project_app.assert_not_called()
            remote_client_class.assert_called_once_with(target="localhost:50052")
            self.assertIs(context.project_app, None)
            self.assertIs(context.project_client, remote_client)
            self.assertIs(create_ingestion_app.await_args.kwargs["project_documents"], remote_client)

            await context.shutdown()
            ingestion_app.shutdown.assert_awaited_once()
            remote_client.shutdown.assert_awaited_once()


class _FakeRemoteProjectClient:
    def __init__(self) -> None:
        self.shutdown = AsyncMock()


if __name__ == "__main__":
    unittest.main()
