"""Ingestion service server tests."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from shared.queue import LocalQueueBroker, QueueMessage
from ingestion_service.server import create_app


class IngestionServiceServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_app_consumes_ingest_request(self) -> None:
        broker = LocalQueueBroker()
        project_documents = AsyncMock()
        app = await create_app(
            queue=broker,
            project_documents=project_documents,
            enabled=True,
            topic="ingestion.requests",
        )

        await broker.publish(
            QueueMessage(
                topic="ingestion.requests",
                key="job1",
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                },
            )
        )
        await asyncio.wait_for(broker.join("ingestion.requests"), timeout=1)

        project_documents.ingest.assert_awaited_once()
        self.assertEqual(app.consumer.topic, "ingestion.requests")
        await app.shutdown()

    async def test_disabled_app_has_no_consumer(self) -> None:
        broker = LocalQueueBroker()
        app = await create_app(
            queue=broker,
            project_documents=AsyncMock(),
            enabled=False,
            topic="ingestion.requests",
        )

        self.assertIsNone(app.consumer)
        await app.shutdown()


if __name__ == "__main__":
    unittest.main()
