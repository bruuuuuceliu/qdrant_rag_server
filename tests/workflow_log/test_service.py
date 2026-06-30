"""Workflow log service tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from workflow_log_service import (
    SQLiteWorkflowLogRepository,
    WorkflowLogEntry,
)


class SQLiteWorkflowLogRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_persists_entries_across_instances(self) -> None:
        with TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "workflow_log.db"
            repository = SQLiteWorkflowLogRepository(db_path)
            await repository.initialize()
            await repository.append(
                WorkflowLogEntry(
                    event="ingest_completed",
                    job_id="job1",
                    status="completed",
                    project_id="p1",
                    user_id="u1",
                    kb_id="kb",
                    doc_id="d1",
                    data_type="project_document",
                    headers={"correlation_id": "job1"},
                    payload={"event": "ingest_completed", "job_id": "job1"},
                )
            )

            reopened = SQLiteWorkflowLogRepository(db_path)
            await reopened.initialize()
            entries = await reopened.list_by_job("job1")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event, "ingest_completed")
        self.assertEqual(entries[0].headers["correlation_id"], "job1")
        self.assertEqual(entries[0].payload["job_id"], "job1")


if __name__ == "__main__":
    unittest.main()
