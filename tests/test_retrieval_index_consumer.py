"""Retrieval indexing queue consumer tests."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from retrieval_service.indexing import RetrievalIndexCommand, RetrievalIndexConsumer
from shared.queue import LocalQueueBroker, QueueMessage


class RetrievalIndexCommandTest(unittest.TestCase):
    def test_parses_payload_into_neutral_index_request(self) -> None:
        command = RetrievalIndexCommand.from_payload(
            {
                "request_id": "req1",
                "response_topic": "retrieval.index.requests.responses.req1",
                "job_id": "job1",
                "collection_name": "rag_p1_v1",
                "chunks": [
                    {
                        "document_id": "d1",
                        "chunk_id": "c1",
                        "chunk_index": 0,
                        "text": "hello",
                        "data_type": "project_document",
                        "content_hash": "hash1",
                        "chunker_version": "v1",
                        "metadata": {"section": 1},
                    }
                ],
                "retrieval_config": {"mode": "hybrid"},
            },
            fallback_request_id="fallback",
        )

        self.assertEqual(command.request_id, "req1")
        self.assertEqual(command.job_id, "job1")
        self.assertEqual(command.collection_name, "rag_p1_v1")
        self.assertEqual(command.chunks[0].chunk_id, "c1")
        self.assertEqual(command.payloads[0].payload_id, "c1")
        self.assertEqual(command.to_index_request().job_id, "job1")

    def test_rejects_missing_collection_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "collection_name"):
            RetrievalIndexCommand.from_payload(
                {
                    "request_id": "req1",
                    "job_id": "job1",
                    "chunks": [],
                    "payloads": [],
                    "retrieval_config": {},
                },
                fallback_request_id="fallback",
            )

    def test_rejects_blank_collection_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "collection_name"):
            RetrievalIndexCommand.from_payload(
                {
                    "request_id": "req1",
                    "collection_name": "",
                    "chunks": [],
                    "payloads": [],
                    "retrieval_config": {},
                },
                fallback_request_id="fallback",
            )


class RetrievalIndexConsumerTest(unittest.IsolatedAsyncioTestCase):
    async def test_processes_request_and_publishes_response(self) -> None:
        broker = LocalQueueBroker()
        indexing_service = _FakeIndexingService()
        consumer = RetrievalIndexConsumer(
            queue=broker,
            indexing_service=indexing_service,
            topic="retrieval.index.requests",
        )
        consumer.start()

        await broker.publish(
            QueueMessage(
                topic="retrieval.index.requests",
                key="req1",
                payload={
                    "request_id": "req1",
                    "response_topic": "retrieval.index.requests.responses.req1",
                    "job_id": "job1",
                    "collection_name": "rag_p1_v1",
                    "chunks": [
                        {
                            "document_id": "d1",
                            "chunk_id": "c1",
                            "chunk_index": 0,
                            "text": "hello",
                            "data_type": "project_document",
                            "chunker_version": "v1",
                        }
                    ],
                    "payloads": [],
                    "retrieval_config": {},
                },
            )
        )

        response = await asyncio.wait_for(
            broker.consume("retrieval.index.requests.responses.req1"),
            timeout=1,
        )
        broker.task_done("retrieval.index.requests.responses.req1")
        await asyncio.wait_for(indexing_service.seen.wait(), timeout=1)

        self.assertTrue(response.payload["ok"])
        self.assertEqual(response.payload["result"]["chunk_count"], 1)
        self.assertEqual(indexing_service.request.collection_name, "rag_p1_v1")
        self.assertEqual(indexing_service.request.job_id, "job1")
        await consumer.stop()

    async def test_failed_request_publishes_error(self) -> None:
        broker = LocalQueueBroker()
        indexing_service = _FailingIndexingService()
        consumer = RetrievalIndexConsumer(
            queue=broker,
            indexing_service=indexing_service,
            topic="retrieval.index.requests",
        )
        consumer.start()

        await broker.publish(
            QueueMessage(
                topic="retrieval.index.requests",
                key="req1",
                payload={
                    "request_id": "req1",
                    "response_topic": "retrieval.index.requests.responses.req1",
                    "job_id": "job1",
                    "collection_name": "rag_p1_v1",
                    "chunks": [],
                    "payloads": [],
                    "retrieval_config": {},
                },
            )
        )

        response = await asyncio.wait_for(
            broker.consume("retrieval.index.requests.responses.req1"),
            timeout=1,
        )
        broker.task_done("retrieval.index.requests.responses.req1")

        self.assertFalse(response.payload["ok"])
        self.assertEqual(response.payload["error"]["message"], "index failed")
        await consumer.stop()

    async def test_invalid_command_publishes_error(self) -> None:
        broker = LocalQueueBroker()
        indexing_service = _FakeIndexingService()
        consumer = RetrievalIndexConsumer(
            queue=broker,
            indexing_service=indexing_service,
            topic="retrieval.index.requests",
        )
        consumer.start()

        await broker.publish(
            QueueMessage(
                topic="retrieval.index.requests",
                key="req1",
                payload={
                    "request_id": "req1",
                    "response_topic": "retrieval.index.requests.responses.req1",
                    "job_id": "job1",
                    "chunks": [],
                    "payloads": [],
                    "retrieval_config": {},
                },
            )
        )

        response = await asyncio.wait_for(
            broker.consume("retrieval.index.requests.responses.req1"),
            timeout=1,
        )
        broker.task_done("retrieval.index.requests.responses.req1")

        self.assertFalse(response.payload["ok"])
        self.assertIn("collection_name", response.payload["error"]["message"])
        self.assertIsNone(indexing_service.request)
        await consumer.stop()

    async def test_invalid_command_publishes_error(self) -> None:
        broker = LocalQueueBroker()
        indexing_service = _FakeIndexingService()
        consumer = RetrievalIndexConsumer(
            queue=broker,
            indexing_service=indexing_service,
            topic="retrieval.index.requests",
        )
        consumer.start()

        await broker.publish(
            QueueMessage(
                topic="retrieval.index.requests",
                key="req1",
                payload={
                    "request_id": "req1",
                    "response_topic": "retrieval.index.requests.responses.req1",
                    "job_id": "job1",
                    "collection_name": "",
                    "chunks": [],
                    "payloads": [],
                    "retrieval_config": {},
                },
            )
        )

        response = await asyncio.wait_for(
            broker.consume("retrieval.index.requests.responses.req1"),
            timeout=1,
        )
        broker.task_done("retrieval.index.requests.responses.req1")

        self.assertFalse(response.payload["ok"])
        self.assertIn("collection_name", response.payload["error"]["message"])
        self.assertIsNone(indexing_service.request)
        await consumer.stop()


class _FakeIndexingService:
    def __init__(self) -> None:
        self.seen = asyncio.Event()
        self.request = None

    async def index_chunks(self, request):
        self.request = request
        self.seen.set()
        return SimpleNamespace(chunk_count=len(request.chunks), dense_enabled=True, sparse_enabled=False)


class _FailingIndexingService:
    async def index_chunks(self, request):
        raise RuntimeError("index failed")


if __name__ == "__main__":
    unittest.main()
