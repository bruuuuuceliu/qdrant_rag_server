"""Project document task orchestration tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from project_service.tasks import ProjectDocumentTaskService


class ProjectDocumentTaskServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_ingest_plans_then_schedules_executor(self) -> None:
        planning = _Planning()
        ingest_executor = _IngestExecutor()
        service = ProjectDocumentTaskService(
            planning=planning,
            ingestion=ingest_executor,
            retrieval=_RetrievalExecutor(),
        )

        result = await service.start_document_ingest_task("request")

        self.assertEqual(result, "scheduled")
        planning.plan_ingest.assert_awaited_once_with("request")
        ingest_executor.start_ingest.assert_awaited_once_with(planning.ingest_plan)

    async def test_search_plans_then_uses_project_retrieval_executor(self) -> None:
        planning = _Planning()
        retrieval_executor = _RetrievalExecutor()
        service = ProjectDocumentTaskService(
            planning=planning,
            ingestion=_IngestExecutor(),
            retrieval=retrieval_executor,
        )

        result = await service.search_documents("request")

        self.assertEqual(result, "search-result")
        planning.plan_search.assert_awaited_once_with("request")
        retrieval_executor.search.assert_awaited_once_with(planning.search_plan)

    async def test_status_reads_from_status_reader(self) -> None:
        status_reader = _StatusReader()
        service = ProjectDocumentTaskService(
            planning=_Planning(),
            ingestion=status_reader,
            retrieval=_RetrievalExecutor(),
        )

        result = await service.get_document_task_status("job1")

        self.assertEqual(result, "status:job1")
        status_reader.get_status.assert_awaited_once_with("job1")

    async def test_delete_plans_then_uses_project_retrieval_executor(self) -> None:
        planning = _Planning()
        retrieval_executor = _RetrievalExecutor()
        service = ProjectDocumentTaskService(
            planning=planning,
            ingestion=_IngestExecutor(),
            retrieval=retrieval_executor,
        )

        result = await service.delete_document("request")

        self.assertEqual(result, "deleted")
        planning.plan_delete.assert_awaited_once_with("request")
        retrieval_executor.delete_document.assert_awaited_once_with(
            planning.delete_plan,
        )


class _Plan:
    def __init__(self, raw_plan: object) -> None:
        self.raw_plan = raw_plan
        self.user_id = "u1"
        self.kb_id = "kb"
        self.doc_id = "d1"


class _Planning:
    def __init__(self) -> None:
        self.ingest_plan = _Plan("raw-ingest-plan")
        self.search_plan = _Plan("raw-search-plan")
        self.delete_plan = _Plan("raw-delete-plan")
        self.plan_ingest = AsyncMock(return_value=self.ingest_plan)
        self.plan_search = AsyncMock(return_value=self.search_plan)
        self.plan_delete = AsyncMock(return_value=self.delete_plan)


class _IngestExecutor:
    def __init__(self) -> None:
        self.start_ingest = AsyncMock(return_value="scheduled")

    async def get_status(self, job_id: str) -> str:
        return f"status:{job_id}"


class _RetrievalExecutor:
    def __init__(self) -> None:
        self.search = AsyncMock(return_value="search-result")
        self.delete_document = AsyncMock(return_value="deleted")


class _StatusReader:
    def __init__(self) -> None:
        self.get_status = AsyncMock(return_value="status:job1")


if __name__ == "__main__":
    unittest.main()
