"""Retrieval API queue app context tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from retrieval_service.retrieval import RetrievalSearchResult
from retrieval_service.server import RetrievalApiQueueClient, create_queue_app
from shared.queue import LocalQueueBroker


class RetrievalApiQueueAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_queue_app_processes_requests(self) -> None:
        queue = LocalQueueBroker()
        service = _RetrievalService()
        app = await create_queue_app(
            queue=queue,
            retrieval_service=service,
            enabled=True,
            topic="retrieval.api.requests",
        )
        client = RetrievalApiQueueClient(queue=queue, response_timeout=1)

        try:
            response = await client.search(
                {
                    "request_id": "req-search",
                    "project_id": "p1",
                    "user_id": "u1",
                    "query_text": "hello",
                    "collection_name": "rag_p1_v1",
                    "retrieval_filter": {
                        "project_id": "p1",
                        "allowed_user_ids": ["u1"],
                    },
                }
            )
        finally:
            await app.shutdown()

        self.assertTrue(app.enabled)
        self.assertEqual(app.topic, "retrieval.api.requests")
        self.assertIsNotNone(app.consumer)
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["chunks"], [{"text": "answer"}])
        service.search.assert_awaited_once()
        service.shutdown.assert_awaited_once()

    async def test_disabled_queue_app_does_not_start_consumer(self) -> None:
        queue = LocalQueueBroker()
        service = _RetrievalService()
        app = await create_queue_app(
            queue=queue,
            retrieval_service=service,
            enabled=False,
            topic="retrieval.api.requests",
        )

        await app.shutdown()

        self.assertFalse(app.enabled)
        self.assertIsNone(app.consumer)
        service.shutdown.assert_awaited_once()


class _RetrievalService:
    def __init__(self) -> None:
        self.search = AsyncMock(
            return_value=RetrievalSearchResult(
                chunks=[{"text": "answer"}],
                elapsed_ms=3,
            )
        )
        self.delete_document = AsyncMock(return_value=None)
        self.get_raw_document = AsyncMock(return_value=None)
        self.shutdown = AsyncMock()


if __name__ == "__main__":
    unittest.main()
