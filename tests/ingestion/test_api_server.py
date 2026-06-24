"""Ingestion API server context tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from ingestion_service.schemas import IngestionJob
from ingestion_service.server import create_api_app
from shared.contracts import JobStatus


class IngestionApiServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_server_context_dispatches_status_and_health(self) -> None:
        job = IngestionJob(
            job_id="job1",
            source_uri="memory://doc",
            document_id="doc1",
            status=JobStatus.PENDING,
        )
        app = _App(jobs=_Jobs({"job1": job}))
        context = await create_api_app(ingestion_app=app)

        status = await context.get_status({"job_id": "job1"})
        health = await context.health()

        self.assertTrue(status["ok"])
        self.assertEqual(status["result"]["job"]["job_id"], "job1")
        self.assertTrue(health["ok"])
        self.assertEqual(health["result"]["topic"], "ingestion.requests")

        await context.shutdown()
        app.shutdown.assert_awaited_once()


class _Jobs:
    def __init__(self, jobs: dict[str, IngestionJob]) -> None:
        self.jobs = jobs

    async def get(self, job_id: str):
        return self.jobs.get(job_id)


class _App:
    def __init__(self, *, jobs) -> None:
        self.jobs = jobs
        self.enabled = True
        self.topic = "ingestion.requests"
        self.consumer = object()
        self.shutdown = AsyncMock()


if __name__ == "__main__":
    unittest.main()
