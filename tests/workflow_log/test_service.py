"""Workflow log service tests."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.queue import LocalQueueBroker, QueueMessage
from workflow_log_service import (
    MemoryWorkflowLogRepository,
    SQLiteWorkflowLogRepository,
    WorkflowLogConsumer,
    WorkflowLogEntry,
)
from workflow_log_service.server import create_app as create_workflow_log_app


class WorkflowLogConsumerTest(unittest.IsolatedAsyncioTestCase):
    async def test_consumes_queue_message_into_repository(self) -> None:
        broker = LocalQueueBroker()
        repository = MemoryWorkflowLogRepository()
        consumer = WorkflowLogConsumer(
            queue=broker,
            repository=repository,
            topic="ingestion.events",
        )
        consumer.start()

        await broker.publish(
            QueueMessage(
                topic="ingestion.events",
                key="job1",
                payload={
                    "event": "ingest_completed",
                    "job_id": "job1",
                    "status": "completed",
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                    "data_type": "project_document",
                    "content_hash": "hash1",
                    "raw_storage_key": "raw/p1/d1",
                    "error": "",
                },
                headers={"correlation_id": "job1"},
            )
        )
        await asyncio.wait_for(broker.join("ingestion.events"), timeout=1)

        entries = await repository.list_by_job("job1")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event, "ingest_completed")
        self.assertEqual(entries[0].status, "completed")
        self.assertEqual(entries[0].project_id, "p1")
        self.assertEqual(entries[0].headers["correlation_id"], "job1")

        await consumer.stop()

    async def test_stop_is_safe_while_waiting_for_message(self) -> None:
        broker = LocalQueueBroker()
        repository = MemoryWorkflowLogRepository()
        consumer = WorkflowLogConsumer(
            queue=broker,
            repository=repository,
            topic="ingestion.events",
        )
        consumer.start()

        await consumer.stop()

        self.assertEqual(await repository.list_all(), [])


class SQLiteWorkflowLogRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_persists_entries_across_instances(self) -> None:
        with TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "workflow_log.db"
            repository = SQLiteWorkflowLogRepository(db_path)
            await repository.initialize()
            await repository.append(
                WorkflowLogEntry(
                    event="ingest_completed",
                    job_id="job1",
                    status="completed",
                    project_id="p1",
                    user_id="u1",
                    kb_id="kb",
                    doc_id="d1",
                    data_type="project_document",
                    headers={"correlation_id": "job1"},
                    payload={"event": "ingest_completed", "job_id": "job1"},
                )
            )

            reopened = SQLiteWorkflowLogRepository(db_path)
            await reopened.initialize()
            entries = await reopened.list_by_job("job1")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event, "ingest_completed")
        self.assertEqual(entries[0].headers["correlation_id"], "job1")
        self.assertEqual(entries[0].payload["job_id"], "job1")


class WorkflowLogAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_app_consumes_events(self) -> None:
        broker = LocalQueueBroker()
        with TemporaryDirectory() as tempdir:
            app = await create_workflow_log_app(
                queue=broker,
                enabled=True,
                topic="ingestion.events",
                db_path=Path(tempdir) / "workflow_log.db",
            )
            await broker.publish(
                QueueMessage(
                    topic="ingestion.events",
                    key="job1",
                    payload={
                        "event": "ingest_running",
                        "job_id": "job1",
                        "status": "running",
                        "project_id": "p1",
                        "user_id": "u1",
                    },
                )
            )
            await asyncio.wait_for(broker.join("ingestion.events"), timeout=1)
            entries = await app.repository.list_by_job("job1")
            await app.shutdown()

        self.assertTrue(app.enabled)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event, "ingest_running")

    async def test_disabled_app_does_not_start_consumer(self) -> None:
        broker = LocalQueueBroker()
        app = await create_workflow_log_app(
            queue=broker,
            enabled=False,
            topic="ingestion.events",
        )

        self.assertFalse(app.enabled)
        self.assertIsNone(app.consumer)
        await app.shutdown()


if __name__ == "__main__":
    unittest.main()
