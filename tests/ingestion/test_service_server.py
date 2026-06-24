"""Ingestion service server tests."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from ingestion_service.jobs import MemoryIngestionJobRepository
from ingestion_service.service import IngestionService
from retrieval_service.indexing import RetrievalIndexCommand, RetrievalIndexConsumer
from shared.queue import LocalQueueBroker, QueueMessage
from ingestion_service.server import create_app


class IngestionServiceServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_app_consumes_ingest_request(self) -> None:
        broker = LocalQueueBroker()
        retrieval_queue = LocalQueueBroker()
        jobs = MemoryIngestionJobRepository()
        indexing_service = _FakeIndexingService()
        index_consumer = RetrievalIndexConsumer(
            queue=retrieval_queue,
            indexing_service=indexing_service,
            topic="retrieval.index.requests",
        )
        index_consumer.start()
        app = await create_app(
            queue=broker,
            jobs=jobs,
            ingestion_service=IngestionService(),
            retrieval_queue=retrieval_queue,
            retrieval_index_response_timeout=1,
            enabled=True,
            topic="ingestion.requests",
        )

        response_topic = "ingestion.requests.responses.job1"
        await broker.publish(
            QueueMessage(
                topic="ingestion.requests",
                key="job1",
                payload={
                    "request_id": "job1",
                    "response_topic": response_topic,
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                    "source_uri": "memory://d1",
                    "content_type": "text/plain",
                    "raw_text": "queued raw text",
                    "metadata": {
                        "collection_name": "rag_p1_v1",
                        "placement_plan": {
                            "placement_version": 4,
                            "targets": [{"shard_id": "retrieval-01"}],
                        },
                    },
                },
            )
        )

        try:
            response = await asyncio.wait_for(
                broker.consume(response_topic), timeout=1
            )
            broker.task_done(response_topic)
            await asyncio.wait_for(indexing_service.seen.wait(), timeout=1)
        finally:
            await index_consumer.stop()

        self.assertTrue(response.payload["ok"])
        self.assertEqual(response.payload["result"]["status"], "completed")
        self.assertEqual(response.payload["result"]["job_id"], "job1")
        job = await jobs.get("job1")
        self.assertIsNotNone(job)
        self.assertEqual(job.status.value, "completed")
        self.assertEqual(job.source_uri, "memory://d1")
        self.assertEqual(job.document_id, "d1")
        self.assertEqual(job.metadata["request_id"], "job1")
        self.assertEqual(job.metadata["prepared_chunk_count"], 1)
        self.assertEqual(job.metadata["raw_content_length"], len(b"queued raw text"))
        self.assertEqual(job.metadata["content_type"], "text/plain")
        self.assertEqual(job.metadata["chunker_versions"], ["v1"])
        self.assertEqual(job.metadata["indexed_chunk_count"], 1)
        self.assertEqual(indexing_service.request.job_id, "job1")
        self.assertEqual(indexing_service.request.collection_name, "rag_p1_v1")
        command = indexing_service.command
        self.assertEqual(command.chunks[0].text, "queued raw text")
        self.assertEqual(command.payloads[0].payload_id, command.chunks[0].chunk_id)
        self.assertEqual(command.placement_plan["placement_version"], 4)
        self.assertEqual(app.consumer.topic, "ingestion.requests")
        self.assertIs(app.jobs, jobs)
        await app.shutdown()

    async def test_retrieval_index_failure_marks_job_failed(self) -> None:
        broker = LocalQueueBroker()
        retrieval_queue = LocalQueueBroker()
        jobs = MemoryIngestionJobRepository()
        index_consumer = RetrievalIndexConsumer(
            queue=retrieval_queue,
            indexing_service=_FailingIndexingService(),
            topic="retrieval.index.requests",
        )
        index_consumer.start()
        app = await create_app(
            queue=broker,
            jobs=jobs,
            ingestion_service=IngestionService(),
            retrieval_queue=retrieval_queue,
            retrieval_index_response_timeout=1,
            enabled=True,
            topic="ingestion.requests",
        )

        await broker.publish(
            QueueMessage(
                topic="ingestion.requests",
                key="job1",
                payload={
                    "request_id": "job1",
                    "response_topic": "ingestion.requests.responses.job1",
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                    "source_uri": "memory://d1",
                    "content_type": "text/plain",
                    "raw_text": "queued raw text",
                    "metadata": {"collection_name": "rag_p1_v1"},
                },
            )
        )

        try:
            response = await asyncio.wait_for(
                broker.consume("ingestion.requests.responses.job1"), timeout=1
            )
            broker.task_done("ingestion.requests.responses.job1")
        finally:
            await index_consumer.stop()

        self.assertFalse(response.payload["ok"])
        self.assertEqual(response.payload["error"]["code"], "INTERNAL_ERROR")
        job = await jobs.get("job1")
        self.assertIsNotNone(job)
        self.assertEqual(job.status.value, "failed")
        self.assertIn("index failed", job.error)
        await app.shutdown()

    async def test_retrieval_queue_requires_collection_name(self) -> None:
        broker = LocalQueueBroker()
        retrieval_queue = LocalQueueBroker()
        jobs = MemoryIngestionJobRepository()
        app = await create_app(
            queue=broker,
            jobs=jobs,
            ingestion_service=IngestionService(),
            retrieval_queue=retrieval_queue,
            enabled=True,
            topic="ingestion.requests",
        )

        await broker.publish(
            QueueMessage(
                topic="ingestion.requests",
                key="job1",
                payload={
                    "request_id": "job1",
                    "response_topic": "ingestion.requests.responses.job1",
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                    "source_uri": "memory://d1",
                    "content_type": "text/plain",
                    "raw_text": "queued raw text",
                },
            )
        )

        response = await asyncio.wait_for(
            broker.consume("ingestion.requests.responses.job1"), timeout=1
        )
        broker.task_done("ingestion.requests.responses.job1")

        self.assertFalse(response.payload["ok"])
        self.assertEqual(response.payload["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("collection_name", response.payload["error"]["message"])
        await app.shutdown()

    async def test_disabled_app_has_no_consumer(self) -> None:
        broker = LocalQueueBroker()
        app = await create_app(
            queue=broker,
            jobs=MemoryIngestionJobRepository(),
            ingestion_service=IngestionService(),
            retrieval_queue=LocalQueueBroker(),
            enabled=False,
            topic="ingestion.requests",
        )

        self.assertIsNone(app.consumer)
        self.assertIsNotNone(app.jobs)
        await app.shutdown()

    async def test_enabled_app_requires_job_storage_preparation_and_index_queue(self) -> None:
        broker = LocalQueueBroker()

        with self.assertRaisesRegex(ValueError, "job repository"):
            await create_app(
                queue=broker,
                jobs=None,
                ingestion_service=IngestionService(),
                retrieval_queue=LocalQueueBroker(),
                enabled=True,
            )
        with self.assertRaisesRegex(ValueError, "ingestion service"):
            await create_app(
                queue=broker,
                jobs=MemoryIngestionJobRepository(),
                ingestion_service=None,
                retrieval_queue=LocalQueueBroker(),
                enabled=True,
            )
        with self.assertRaisesRegex(ValueError, "retrieval index queue"):
            await create_app(
                queue=broker,
                jobs=MemoryIngestionJobRepository(),
                ingestion_service=IngestionService(),
                retrieval_queue=None,
                enabled=True,
            )


class _FakeIndexingService:
    def __init__(self) -> None:
        self.seen = asyncio.Event()
        self.request = None
        self.command = None

    async def index_chunks(self, request):
        self.request = request
        self.command = RetrievalIndexCommand.from_payload(
            {
                "request_id": request.job_id,
                "job_id": request.job_id,
                "collection_name": request.collection_name,
                "chunks": [
                    {
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.chunk_id,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "data_type": chunk.data_type,
                        "content_hash": chunk.content_hash,
                        "chunker_version": chunk.chunker_version,
                        "metadata": chunk.metadata,
                    }
                    for chunk in request.chunks
                ],
                "payloads": [
                    {
                        "payload_id": payload.payload_id,
                        "document_id": payload.document_id,
                        "chunk_id": payload.chunk_id,
                        "chunk_index": payload.chunk_index,
                        "text": payload.text,
                        "data_type": payload.data_type,
                        "content_hash": payload.content_hash,
                        "embedding_version": payload.embedding_version,
                        "chunker_version": payload.chunker_version,
                        "metadata": payload.metadata,
                    }
                    for payload in request.payloads
                ],
                "retrieval_config": request.retrieval_config,
                "placement_plan": request.placement_plan,
            },
            fallback_request_id=request.job_id,
        )
        self.seen.set()
        return SimpleNamespace(
            chunk_count=len(request.chunks),
            dense_enabled=True,
            sparse_enabled=False,
        )


class _FailingIndexingService:
    async def index_chunks(self, request):
        raise RuntimeError("index failed")


if __name__ == "__main__":
    unittest.main()
