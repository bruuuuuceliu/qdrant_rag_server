"""Retrieval indexing app context tests."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from retrieval_service.indexing import create_app
from shared.queue import LocalQueueBroker, QueueMessage


class RetrievalIndexAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_app_starts_consumer(self) -> None:
        broker = LocalQueueBroker()
        indexing_service = _FakeIndexingService()
        app = await create_app(
            queue=broker,
            indexing_service=indexing_service,
            enabled=True,
            topic="custom.index",
        )

        await broker.publish(
            QueueMessage(
                topic="custom.index",
                key="req1",
                payload={
                    "request_id": "req1",
                    "response_topic": "custom.index.responses.req1",
                    "job_id": "job1",
                    "collection_name": "rag_p1_v1",
                    "chunks": [
                        {
                            "chunk_id": "c1",
                            "chunk_index": 0,
                            "text": "hello",
                        }
                    ],
                    "payloads": [],
                    "retrieval_config": {},
                },
            )
        )

        response = await asyncio.wait_for(
            broker.consume("custom.index.responses.req1"), timeout=1
        )
        broker.task_done("custom.index.responses.req1")

        self.assertTrue(app.enabled)
        self.assertEqual(app.topic, "custom.index")
        self.assertIsNotNone(app.consumer)
        self.assertTrue(response.payload["ok"])
        self.assertEqual(indexing_service.request.collection_name, "rag_p1_v1")
        await app.shutdown()

    async def test_disabled_app_has_no_consumer(self) -> None:
        app = await create_app(
            queue=LocalQueueBroker(),
            indexing_service=_FakeIndexingService(),
            enabled=False,
            topic="custom.index",
        )

        self.assertFalse(app.enabled)
        self.assertEqual(app.topic, "custom.index")
        self.assertIsNone(app.consumer)
        await app.shutdown()


class _FakeIndexingService:
    request = None

    async def index_chunks(self, request):
        self.request = request
        return SimpleNamespace(chunk_count=len(request.chunks), dense_enabled=True, sparse_enabled=False)


if __name__ == "__main__":
    unittest.main()
