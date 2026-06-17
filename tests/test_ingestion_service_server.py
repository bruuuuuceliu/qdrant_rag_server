"""Ingestion service server tests."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ingestion_service.jobs import MemoryIngestionJobRepository
from ingestion_service.service import IngestionService
from retrieval_service.indexing import RetrievalIndexCommand
from shared.queue import LocalQueueBroker, QueueMessage
from ingestion_service.server import create_app


class IngestionServiceServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_app_consumes_ingest_request(self) -> None:
        broker = LocalQueueBroker()
        retrieval_queue = LocalQueueBroker()
        project_documents = AsyncMock()
        project_documents.ingest.return_value = SimpleNamespace(
            job_id="engine-job-1",
            status="pending",
            doc_id="d1",
            project_id="p1",
            error="",
        )
        jobs = MemoryIngestionJobRepository()
        seen_job = asyncio.Event()

        async def ingest(request: object) -> SimpleNamespace:
            job = await jobs.get("job1")
            self.assertIsNotNone(job)
            self.assertEqual(job.source_uri, "memory://d1")
            self.assertEqual(job.document_id, "d1")
            self.assertEqual(job.metadata["request_id"], "job1")
            self.assertEqual(job.metadata["prepared_chunk_count"], 1)
            self.assertEqual(job.metadata["handler_name"], "text")
            self.assertEqual(request["raw_text"], "queued raw text")
            seen_job.set()
            return SimpleNamespace(
                job_id="engine-job-1",
                status="pending",
                doc_id="d1",
                project_id="p1",
                error="",
            )

        project_documents.ingest.side_effect = ingest
        app = await create_app(
            queue=broker,
            project_documents=project_documents,
            jobs=jobs,
            ingestion_service=IngestionService(),
            retrieval_queue=retrieval_queue,
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
                    "metadata": {"collection_name": "rag_p1_v1"},
                },
            )
        )

        # Wait for the consumer to schedule ingest and publish the response.
        response = await asyncio.wait_for(
            broker.consume(response_topic), timeout=1
        )
        broker.task_done(response_topic)
        await asyncio.wait_for(seen_job.wait(), timeout=1)

        self.assertTrue(response.payload["ok"])
        self.assertEqual(response.payload["result"]["status"], "pending")
        self.assertEqual(response.payload["result"]["job_id"], "job1")
        job = await jobs.get("job1")
        self.assertIsNotNone(job)
        self.assertEqual(job.status.value, "pending")
        self.assertEqual(job.source_uri, "memory://d1")
        self.assertEqual(job.document_id, "d1")
        self.assertEqual(job.metadata["request_id"], "job1")
        self.assertEqual(job.metadata["prepared_chunk_count"], 1)
        self.assertEqual(job.metadata["raw_content_length"], len(b"queued raw text"))
        self.assertEqual(job.metadata["content_type"], "text/plain")
        self.assertEqual(job.metadata["chunker_versions"], ["v1"])
        index_message = await asyncio.wait_for(
            retrieval_queue.consume("retrieval.index.requests"), timeout=1
        )
        retrieval_queue.task_done("retrieval.index.requests")
        self.assertEqual(index_message.payload["job_id"], "job1")
        self.assertEqual(index_message.payload["collection_name"], "rag_p1_v1")
        self.assertEqual(index_message.payload["chunks"][0]["text"], "queued raw text")
        command = RetrievalIndexCommand.from_payload(
            index_message.payload,
            fallback_request_id=index_message.key,
        )
        self.assertEqual(command.chunks[0].text, "queued raw text")
        self.assertEqual(command.payloads[0].payload_id, command.chunks[0].chunk_id)
        project_documents.ingest.assert_awaited_once()

        self.assertEqual(app.consumer.topic, "ingestion.requests")
        self.assertIs(app.jobs, jobs)
        await app.shutdown()

    async def test_retrieval_queue_requires_collection_name(self) -> None:
        broker = LocalQueueBroker()
        retrieval_queue = LocalQueueBroker()
        project_documents = AsyncMock()
        jobs = MemoryIngestionJobRepository()
        app = await create_app(
            queue=broker,
            project_documents=project_documents,
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
        project_documents.ingest.assert_not_awaited()
        await app.shutdown()

    async def test_disabled_app_has_no_consumer(self) -> None:
        broker = LocalQueueBroker()
        app = await create_app(
            queue=broker,
            project_documents=AsyncMock(),
            jobs=MemoryIngestionJobRepository(),
            enabled=False,
            topic="ingestion.requests",
        )

        self.assertIsNone(app.consumer)
        self.assertIsNotNone(app.jobs)
        await app.shutdown()

    async def test_app_without_job_repository_keeps_delegated_job_id(self) -> None:
        broker = LocalQueueBroker()
        project_documents = AsyncMock()
        project_documents.ingest.return_value = SimpleNamespace(
            job_id="engine-job-1",
            status="pending",
            doc_id="d1",
            project_id="p1",
            error="",
        )
        app = await create_app(
            queue=broker,
            project_documents=project_documents,
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
                    "request": {
                        "project_id": "p1",
                        "user_id": "u1",
                        "kb_id": "kb",
                        "doc_id": "d1",
                        "source_uri": "memory://d1",
                        "metadata": {"data_type": "project_document"},
                    },
                },
            )
        )

        response = await asyncio.wait_for(broker.consume(response_topic), timeout=1)
        broker.task_done(response_topic)

        self.assertTrue(response.payload["ok"])
        self.assertEqual(response.payload["result"]["job_id"], "engine-job-1")
        self.assertEqual(project_documents.ingest.await_args.args[0]["doc_id"], "d1")
        await app.shutdown()

    async def test_app_without_retrieval_queue_skips_publication(self) -> None:
        broker = LocalQueueBroker()
        project_documents = AsyncMock()
        project_documents.ingest.return_value = SimpleNamespace(
            job_id="engine-job-1",
            status="pending",
            doc_id="d1",
            project_id="p1",
            error="",
        )
        jobs = MemoryIngestionJobRepository()
        app = await create_app(
            queue=broker,
            project_documents=project_documents,
            jobs=jobs,
            ingestion_service=IngestionService(),
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

        self.assertTrue(response.payload["ok"])
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(
                broker.consume("retrieval.index.requests"), timeout=0.2
            )
        await app.shutdown()


if __name__ == "__main__":
    unittest.main()
