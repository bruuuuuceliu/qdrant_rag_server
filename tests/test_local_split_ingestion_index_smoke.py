"""Local split-service ingestion-to-index queue smoke test."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from ingestion_service.jobs import MemoryIngestionJobRepository
from ingestion_service.server import create_app as create_ingestion_app
from ingestion_service.service import IngestionService
from retrieval_service.indexing import RetrievalIndexConsumer
from shared.queue import QueueMessage, SQLiteQueueBroker


class LocalSplitIngestionIndexSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_queue_handoff_from_ingestion_to_retrieval_indexing(self) -> None:
        with TemporaryDirectory() as tempdir:
            queue_db = Path(tempdir) / "queue.db"
            manager_queue = SQLiteQueueBroker(queue_db, poll_interval=0.01)
            ingestion_retrieval_queue = SQLiteQueueBroker(queue_db, poll_interval=0.01)
            retrieval_worker_queue = SQLiteQueueBroker(queue_db, poll_interval=0.01)
            jobs = MemoryIngestionJobRepository()
            indexing_service = _FakeIndexingService()
            ingestion_app = await create_ingestion_app(
                queue=manager_queue,
                jobs=jobs,
                ingestion_service=IngestionService(),
                retrieval_queue=ingestion_retrieval_queue,
                retrieval_index_topic="retrieval.index.requests",
                enabled=True,
                topic="ingestion.requests",
            )
            index_consumer = RetrievalIndexConsumer(
                queue=retrieval_worker_queue,
                indexing_service=indexing_service,
                topic="retrieval.index.requests",
            )
            index_consumer.start()

            try:
                await manager_queue.publish(
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
                            "raw_text": "split service text",
                            "metadata": {
                                "collection_name": "rag_p1_v1",
                                "retrieval_config": {},
                            },
                        },
                    )
                )

                response = await asyncio.wait_for(
                    manager_queue.consume("ingestion.requests.responses.job1"),
                    timeout=1,
                )
                manager_queue.task_done("ingestion.requests.responses.job1")
                await asyncio.wait_for(indexing_service.seen.wait(), timeout=1)

                self.assertTrue(response.payload["ok"])
                self.assertEqual(response.payload["result"]["job_id"], "job1")
                self.assertEqual(response.payload["result"]["status"], "completed")
                self.assertEqual(indexing_service.request.job_id, "job1")
                self.assertEqual(
                    indexing_service.request.collection_name,
                    "rag_p1_v1",
                )
                self.assertEqual(
                    indexing_service.request.chunks[0].text,
                    "split service text",
                )
                job = await jobs.get("job1")
                self.assertIsNotNone(job)
                self.assertEqual(job.status.value, "completed")
                self.assertEqual(job.metadata["prepared_chunk_count"], 1)
                self.assertEqual(job.metadata["indexed_chunk_count"], 1)
            finally:
                await index_consumer.stop()
                await ingestion_app.shutdown()

class _FakeIndexingService:
    def __init__(self) -> None:
        self.seen = asyncio.Event()
        self.request = None

    async def index_chunks(self, request):
        self.request = request
        self.seen.set()
        return SimpleNamespace(
            chunk_count=len(request.chunks),
            dense_enabled=True,
            sparse_enabled=False,
        )


if __name__ == "__main__":
    unittest.main()
