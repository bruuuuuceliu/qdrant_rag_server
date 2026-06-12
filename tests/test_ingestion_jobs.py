"""Durable ingestion job repository tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ingestion_service.jobs import SQLiteIngestionJobRepository
from ingestion_service.schemas import IngestionJob
from retrieval_service.core.schemas import JobStatus


class SQLiteIngestionJobRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_persists_job_across_instances(self) -> None:
        with TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "jobs.db"
            repo = SQLiteIngestionJobRepository(path)
            await repo.initialize()
            await repo.create(_job("j1"))

            reopened = SQLiteIngestionJobRepository(path)
            await reopened.initialize()
            job = await reopened.get("j1")

        self.assertIsNotNone(job)
        self.assertEqual(job.job_id, "j1")
        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertEqual(job.metadata["project_id"], "p1")
        self.assertEqual(job.metadata["content_hash"], "hash1")

    async def test_updates_status_and_error(self) -> None:
        with TemporaryDirectory() as tempdir:
            repo = SQLiteIngestionJobRepository(Path(tempdir) / "jobs.db")
            await repo.initialize()
            await repo.create(_job("j1"))
            before = await repo.get("j1")

            running = await repo.update_status("j1", JobStatus.RUNNING)
            failed = await repo.update_status("j1", JobStatus.FAILED, error="bad input")

        self.assertEqual(running.status, JobStatus.RUNNING)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.error, "bad input")
        self.assertGreaterEqual(failed.updated_at, before.updated_at)

    async def test_updates_metadata(self) -> None:
        with TemporaryDirectory() as tempdir:
            repo = SQLiteIngestionJobRepository(Path(tempdir) / "jobs.db")
            await repo.initialize()
            await repo.create(_job("j1"))

            updated = await repo.update_metadata(
                "j1",
                {"content_hash": "parsed-hash", "raw_storage_key": "raw/p1/d1"},
            )

        self.assertEqual(updated.metadata["content_hash"], "parsed-hash")
        self.assertEqual(updated.metadata["raw_storage_key"], "raw/p1/d1")

    async def test_returns_none_for_missing_job(self) -> None:
        with TemporaryDirectory() as tempdir:
            repo = SQLiteIngestionJobRepository(Path(tempdir) / "jobs.db")
            await repo.initialize()

            job = await repo.get("missing")

        self.assertIsNone(job)


def _job(job_id: str) -> IngestionJob:
    return IngestionJob(
        job_id=job_id,
        source_uri="memory://doc",
        document_id="d1",
        metadata={
            "project_id": "p1",
            "user_id": "u1",
            "kb_id": "kb",
            "doc_id": "d1",
            "data_type": "project_document",
            "content_hash": "hash1",
        },
    )


if __name__ == "__main__":
    unittest.main()
