"""Project service client tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from project_service.client import LocalProjectServiceClient
from project_service.gateway.requests import IngestRequest, SearchRequest


class LocalProjectServiceClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_prepares_plan_then_schedules_engine(self) -> None:
        gateway = _Gateway()
        engine = _Engine()
        client = LocalProjectServiceClient(gateway=gateway, engine=engine)
        request = IngestRequest(
            project_id="p1",
            user_id="u1",
            kb_id="kb",
            doc_id="d1",
            source_uri="memory://d1",
            content_type="text/plain",
        )

        result = await client.ingest(request)

        self.assertEqual(result, "scheduled")
        gateway.prepare_ingest.assert_awaited_once_with(request)
        engine.schedule_ingest.assert_awaited_once_with("ingest-plan")

    async def test_search_prepares_plan_then_searches_engine(self) -> None:
        gateway = _Gateway()
        engine = _Engine()
        client = LocalProjectServiceClient(gateway=gateway, engine=engine)
        request = SearchRequest(project_id="p1", user_id="u1", query="hello")

        result = await client.search(request)

        self.assertEqual(result, "search-result")
        gateway.prepare_search.assert_awaited_once_with(request)
        engine.search.assert_awaited_once_with("search-plan")

    async def test_accepts_mapping_requests_at_client_boundary(self) -> None:
        gateway = _Gateway()
        engine = _Engine()
        client = LocalProjectServiceClient(gateway=gateway, engine=engine)

        await client.ingest(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
                "source_uri": "memory://d1",
                "content_type": "text/plain",
            }
        )
        await client.search({"project_id": "p1", "user_id": "u1", "query": "hello"})

        self.assertIsInstance(gateway.prepare_ingest.await_args.args[0], IngestRequest)
        self.assertIsInstance(gateway.prepare_search.await_args.args[0], SearchRequest)

    async def test_ingest_status_delegates_to_engine(self) -> None:
        gateway = _Gateway()
        engine = _Engine()
        client = LocalProjectServiceClient(gateway=gateway, engine=engine)

        result = await client.ingest_status("job1")

        self.assertEqual(result, "status:job1")
        engine.get_ingest_status.assert_awaited_once_with("job1")

    async def test_delete_document_prepares_plan_then_deletes_engine(self) -> None:
        gateway = _Gateway()
        engine = _Engine()
        client = LocalProjectServiceClient(gateway=gateway, engine=engine)

        result = await client.delete_document(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
            }
        )

        self.assertEqual(result, "deleted")
        gateway.prepare_delete.assert_awaited_once()
        engine.delete_document.assert_awaited_once_with(
            config=gateway.delete_plan.config,
            user_id="u1",
            kb_id="kb",
            doc_id="d1",
        )


class _Gateway:
    def __init__(self) -> None:
        self.delete_plan = _DeletePlan(
            request=_DeleteRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
            ),
            config=_Config(),
        )
        self.prepare_ingest = AsyncMock(return_value="ingest-plan")
        self.prepare_search = AsyncMock(return_value="search-plan")
        self.prepare_delete = AsyncMock(return_value=self.delete_plan)


class _Engine:
    def __init__(self) -> None:
        self.schedule_ingest = AsyncMock(return_value="scheduled")
        self.search = AsyncMock(return_value="search-result")
        self.get_ingest_status = AsyncMock(return_value="status:job1")
        self.delete_document = AsyncMock(return_value="deleted")


class _DeleteRequest:
    def __init__(self, *, project_id: str, user_id: str, kb_id: str, doc_id: str) -> None:
        self.project_id = project_id
        self.user_id = user_id
        self.kb_id = kb_id
        self.doc_id = doc_id


class _Config:
    pass


class _DeletePlan:
    def __init__(self, *, request: _DeleteRequest, config: _Config) -> None:
        self.request = request
        self.config = config


if __name__ == "__main__":
    unittest.main()
