"""Retrieval API queue transport tests."""

from __future__ import annotations

import unittest

from retrieval_service.server import (
    RetrievalApiQueueClient,
    RetrievalApiQueueConsumer,
    RetrievalApiQueueTimeoutError,
)
from shared.queue import LocalQueueBroker, QueueMessage


class RetrievalApiQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_client_and_consumer_round_trip_search(self) -> None:
        queue = LocalQueueBroker()
        api = _RetrievalApi()
        consumer = RetrievalApiQueueConsumer(queue=queue, api=api)
        consumer.start()
        client = RetrievalApiQueueClient(queue=queue, response_timeout=1)

        try:
            response = await client.search(
                {
                    "request_id": "req-search",
                    "project_id": "p1",
                    "user_id": "u1",
                    "query_text": "hello",
                }
            )
        finally:
            await consumer.stop()

        self.assertEqual(
            response,
            {
                "request_id": "req-search",
                "ok": True,
                "result": {"chunks": [{"text": "answer"}], "elapsed_ms": 5},
            },
        )
        self.assertEqual(api.search_payload["project_id"], "p1")
        self.assertEqual(api.search_fallback_request_id, "req-search")

    async def test_client_and_consumer_round_trip_delete(self) -> None:
        queue = LocalQueueBroker()
        api = _RetrievalApi()
        consumer = RetrievalApiQueueConsumer(queue=queue, api=api)
        consumer.start()
        client = RetrievalApiQueueClient(queue=queue, response_timeout=1)

        try:
            response = await client.delete_document(
                {
                    "request_id": "req-delete",
                    "request": {
                        "project_id": "p1",
                        "user_id": "u1",
                        "kb_id": "kb",
                        "doc_id": "d1",
                    },
                }
            )
        finally:
            await consumer.stop()

        self.assertEqual(
            response,
            {"request_id": "req-delete", "ok": True, "result": {"deleted": True}},
        )
        self.assertEqual(api.delete_payload["doc_id"], "d1")

    async def test_consumer_returns_validation_error_for_unknown_operation(self) -> None:
        queue = LocalQueueBroker()
        consumer = RetrievalApiQueueConsumer(queue=queue, api=_RetrievalApi())
        consumer.start()

        await queue.publish(
            QueueMessage(
                topic="retrieval.api.requests",
                key="req-bad",
                payload={
                    "request_id": "req-bad",
                    "response_topic": "retrieval.api.responses.req-bad",
                    "operation": "bad_op",
                    "request": {},
                },
            )
        )
        try:
            response = await queue.consume("retrieval.api.responses.req-bad")
        finally:
            await consumer.stop()

        self.assertEqual(response.payload["request_id"], "req-bad")
        self.assertFalse(response.payload["ok"])
        self.assertEqual(response.payload["error"]["code"], "validation_error")
        self.assertFalse(response.payload["error"]["retryable"])
        self.assertIn("bad_op", response.payload["error"]["message"])

    async def test_client_timeout_raises_clear_error(self) -> None:
        queue = LocalQueueBroker()
        client = RetrievalApiQueueClient(queue=queue, response_timeout=0.01)

        with self.assertRaises(RetrievalApiQueueTimeoutError) as raised:
            await client.get_raw_document(
                {
                    "request_id": "req-timeout",
                    "project_id": "p1",
                    "user_id": "u1",
                    "doc_id": "d1",
                }
            )

        self.assertEqual(raised.exception.request_id, "req-timeout")
        self.assertEqual(raised.exception.timeout, 0.01)


class _RetrievalApi:
    def __init__(self) -> None:
        self.search_payload = None
        self.delete_payload = None
        self.raw_payload = None

    async def search(self, payload, *, fallback_request_id: str):
        self.search_payload = payload
        self.search_fallback_request_id = fallback_request_id
        return {
            "request_id": fallback_request_id,
            "ok": True,
            "result": {"chunks": [{"text": "answer"}], "elapsed_ms": 5},
        }

    async def delete_document(self, payload, *, fallback_request_id: str):
        self.delete_payload = payload
        self.delete_fallback_request_id = fallback_request_id
        return {
            "request_id": fallback_request_id,
            "ok": True,
            "result": {"deleted": True},
        }

    async def get_raw_document(self, payload, *, fallback_request_id: str):
        self.raw_payload = payload
        self.raw_fallback_request_id = fallback_request_id
        return {
            "request_id": fallback_request_id,
            "ok": True,
            "result": {"found": False, "content_b64": "", "encoding": "base64"},
        }


if __name__ == "__main__":
    unittest.main()
