"""Ingestion API handler tests."""

from __future__ import annotations

import unittest

from ingestion_service.schemas import IngestionJob
from ingestion_service.server.handler import IngestionApiHandler
from shared.contracts import JobStatus


class IngestionApiHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_status_returns_job_payload(self) -> None:
        job = IngestionJob(
            job_id="job1",
            source_uri="memory://doc",
            document_id="doc1",
            status=JobStatus.COMPLETED,
            metadata={"project_id": "p1"},
        )
        handler = IngestionApiHandler(app=_App(jobs=_Jobs({"job1": job})))

        response = await handler.get_status({"request_id": "req1", "job_id": "job1"})

        self.assertTrue(response["ok"])
        self.assertEqual(response["request_id"], "req1")
        self.assertEqual(response["result"]["job"]["job_id"], "job1")
        self.assertEqual(response["result"]["job"]["status"], JobStatus.COMPLETED.value)

    async def test_get_status_returns_not_found(self) -> None:
        handler = IngestionApiHandler(app=_App(jobs=_Jobs({})))

        response = await handler.get_status({"request_id": "req1", "job_id": "missing"})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "not_found")

    async def test_get_status_returns_unavailable_without_jobs(self) -> None:
        handler = IngestionApiHandler(app=_App(jobs=None))

        response = await handler.get_status({"request_id": "req1", "job_id": "job1"})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unavailable")
        self.assertTrue(response["error"]["retryable"])

    async def test_get_status_returns_validation_error(self) -> None:
        handler = IngestionApiHandler(app=_App(jobs=_Jobs({})))

        response = await handler.get_status({"request_id": "req1"})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "validation_error")

    async def test_health_reports_worker_control_state(self) -> None:
        handler = IngestionApiHandler(app=_App(jobs=_Jobs({}), enabled=True, topic="docs.in"))

        response = await handler.health({"request_id": "health1"})

        self.assertTrue(response["ok"])
        self.assertEqual(response["request_id"], "health1")
        self.assertTrue(response["result"]["enabled"])
        self.assertEqual(response["result"]["topic"], "docs.in")
        self.assertTrue(response["result"]["jobs_configured"])
        self.assertFalse(response["result"]["consumer_running"])


class _Jobs:
    def __init__(self, jobs: dict[str, IngestionJob]) -> None:
        self.jobs = jobs

    async def get(self, job_id: str):
        return self.jobs.get(job_id)


class _App:
    def __init__(self, *, jobs, enabled: bool = False, topic: str = "ingestion.requests") -> None:
        self.jobs = jobs
        self.enabled = enabled
        self.topic = topic
        self.consumer = None


if __name__ == "__main__":
    unittest.main()
