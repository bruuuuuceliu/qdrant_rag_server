"""Project service client tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from project_service.client import (
    LocalProjectServiceClient,
    ProjectPlannedRetrievalApiClient,
    ProjectPlannedRetrievalClient,
    RemoteProjectServiceClient,
)
from project_service.gateway.requests import IngestRequest, SearchRequest
from project_service.schemas import IngestResult, SearchResult
from retrieval_service.core.schemas import JobStatus


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
        gateway.prepare_search.return_value = "search-plan"
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

    async def test_accepts_top_level_raw_text_mapping_at_client_boundary(self) -> None:
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
                "raw_text": "hello",
            }
        )

        request = gateway.prepare_ingest.await_args.args[0]
        self.assertEqual(request.raw_text, "hello")
        self.assertEqual(request.metadata, {})

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


class ProjectPlannedRetrievalClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_prepares_plan_then_uses_retrieval_service(self) -> None:
        gateway = _Gateway()
        retrieval_service = _RetrievalService()
        client = ProjectPlannedRetrievalClient(
            gateway=gateway,
            retrieval_service=retrieval_service,
        )

        result = await client.search(SearchRequest(project_id="p1", user_id="u1", query="hello"))

        self.assertIsInstance(result, SearchResult)
        self.assertEqual(result.chunks, [{"text": "answer"}])
        self.assertEqual(retrieval_service.search_request.collection_name, "rag_p1_v1")
        self.assertEqual(retrieval_service.search_request.query_text, "hello")
        gateway.prepare_search.assert_awaited_once()

    async def test_delete_prepares_plan_then_uses_retrieval_service(self) -> None:
        gateway = _Gateway()
        retrieval_service = _RetrievalService()
        client = ProjectPlannedRetrievalClient(
            gateway=gateway,
            retrieval_service=retrieval_service,
        )

        await client.delete_document(
            {"project_id": "p1", "user_id": "u1", "kb_id": "kb", "doc_id": "d1"}
        )

        self.assertEqual(retrieval_service.delete_request.collection_name, "rag_p1_v1")
        self.assertEqual(retrieval_service.delete_request.doc_id, "d1")
        gateway.prepare_delete.assert_awaited_once()


class ProjectPlannedRetrievalApiClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_prepares_plan_then_uses_retrieval_api(self) -> None:
        gateway = _Gateway()
        retrieval_api = _RetrievalApi()
        client = ProjectPlannedRetrievalApiClient(
            gateway=gateway,
            retrieval_api=retrieval_api,
        )

        result = await client.search(
            _SearchRequest(project_id="p1", user_id="u1", query="hello")
        )

        self.assertIsInstance(result, SearchResult)
        self.assertEqual(result.chunks, [{"text": "answer"}])
        self.assertEqual(result.elapsed_ms, 5)
        self.assertEqual(retrieval_api.search_payload["request_id"], "search:p1:u1")
        self.assertEqual(
            retrieval_api.search_payload["request"]["collection_name"],
            "rag_p1_v1",
        )
        self.assertEqual(
            retrieval_api.search_payload["request"]["query_text"],
            "hello",
        )
        self.assertIs(
            retrieval_api.search_payload["request"]["retrieval_filter"],
            gateway.search_plan.retrieval_filter,
        )

    async def test_delete_prepares_plan_then_uses_retrieval_api(self) -> None:
        gateway = _Gateway()
        retrieval_api = _RetrievalApi()
        client = ProjectPlannedRetrievalApiClient(
            gateway=gateway,
            retrieval_api=retrieval_api,
        )

        result = await client.delete_document(
            _DeleteRequest(project_id="p1", user_id="u1", kb_id="kb", doc_id="d1")
        )

        self.assertIsNone(result)
        self.assertEqual(retrieval_api.delete_payload["request_id"], "delete:p1:u1:kb:d1")
        self.assertEqual(retrieval_api.delete_payload["request"]["doc_id"], "d1")
        self.assertEqual(
            retrieval_api.delete_payload["request"]["collection_name"],
            "rag_p1_v1",
        )

    async def test_failed_retrieval_api_response_raises_runtime_error(self) -> None:
        client = ProjectPlannedRetrievalApiClient(
            gateway=_Gateway(),
            retrieval_api=_RetrievalApi(
                search_response={
                    "request_id": "req",
                    "ok": False,
                    "error": {
                        "code": "validation_error",
                        "message": "bad retrieval filter",
                    },
                }
            ),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "validation_error: bad retrieval filter",
        ):
            await client.search(
                _SearchRequest(project_id="p1", user_id="u1", query="hello")
            )


class RemoteProjectServiceClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_maps_proto_response_to_result(self) -> None:
        stub = _Stub(
            ingest_result=object(),
        )
        remote = RemoteProjectServiceClient(target="localhost:50052", stub=stub)

        result = await remote.ingest(
            IngestRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                source_uri="memory://d1",
                content_type="text/plain",
            )
        )

        self.assertIsInstance(result, IngestResult)
        self.assertEqual(result.job_id, "job1")
        self.assertEqual(result.status, JobStatus.PENDING)
        self.assertEqual(result.project_id, "p1")
        self.assertEqual(stub.ingest_request.project_id, "p1")

    async def test_search_maps_proto_response_to_result(self) -> None:
        stub = _Stub(search_result=object())
        remote = RemoteProjectServiceClient(target="localhost:50052", stub=stub)

        result = await remote.search(
            SearchRequest(project_id="p1", user_id="u1", query="hello")
        )

        self.assertIsInstance(result, SearchResult)
        self.assertEqual(result.elapsed_ms, 7)
        self.assertEqual(result.chunks[0]["chunk_id"], "chunk1")
        self.assertEqual(stub.search_request.project_id, "p1")

    async def test_status_maps_proto_response_to_result(self) -> None:
        stub = _Stub(status_result=object())
        remote = RemoteProjectServiceClient(target="localhost:50052", stub=stub)

        result = await remote.ingest_status("job1")

        self.assertIsInstance(result, IngestResult)
        self.assertEqual(result.job_id, "job1")
        self.assertEqual(result.status, JobStatus.PENDING)


class _Stub:
    def __init__(self, *, ingest_result: object | None = None, search_result: object | None = None, status_result: object | None = None) -> None:
        self.ingest_result = ingest_result
        self.search_result = search_result
        self.status_result = status_result
        self.ingest_request = None
        self.search_request = None

    async def Ingest(self, request):
        self.ingest_request = request
        from project_service.server.grpc.generated import retrieval_service_pb2

        return retrieval_service_pb2.IngestResponse(job_id="job1", status="pending")

    async def Search(self, request):
        self.search_request = request
        from project_service.server.grpc.generated import retrieval_service_pb2

        return retrieval_service_pb2.SearchResponse(
            chunks=[
                retrieval_service_pb2.ChunkResult(
                    project_id="p1",
                    user_id="u1",
                    kb_id="kb",
                    doc_id="d1",
                    chunk_id="chunk1",
                    chunk_index=0,
                    text="hello world",
                    score=0.5,
                )
            ],
            elapsed_ms=7,
            cache_hit=False,
        )

    async def GetIngestJobStatus(self, request):
        from project_service.server.grpc.generated import retrieval_service_pb2

        return retrieval_service_pb2.GetIngestJobStatusResponse(
            job_id=request.job_id,
            status="pending",
            error="",
            doc_id="d1",
        )


class _Gateway:
    def __init__(self) -> None:
        self.search_plan = _SearchPlan(
            request=_SearchRequest(project_id="p1", user_id="u1", query="hello"),
            config=_Config(),
        )
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
        self.prepare_search = AsyncMock(return_value=self.search_plan)
        self.prepare_delete = AsyncMock(return_value=self.delete_plan)


class _Engine:
    def __init__(self) -> None:
        self.schedule_ingest = AsyncMock(return_value="scheduled")
        self.search = AsyncMock(return_value="search-result")
        self.get_ingest_status = AsyncMock(return_value="status:job1")
        self.delete_document = AsyncMock(return_value="deleted")


class _RetrievalService:
    search_request = None
    delete_request = None

    async def search(self, request):
        self.search_request = request
        return _RetrievalSearchResult()

    async def delete_document(self, request):
        self.delete_request = request
        return None


class _RetrievalApi:
    def __init__(
        self,
        *,
        search_response: dict | None = None,
        delete_response: dict | None = None,
    ) -> None:
        self.search_response = search_response or {
            "request_id": "req-search",
            "ok": True,
            "result": {
                "chunks": [{"text": "answer"}],
                "elapsed_ms": 5,
                "cache_hit": False,
            },
        }
        self.delete_response = delete_response or {
            "request_id": "req-delete",
            "ok": True,
            "result": {"deleted": True},
        }
        self.search_payload = None
        self.delete_payload = None

    async def search(self, payload, *, fallback_request_id: str):
        self.search_payload = payload
        self.search_fallback_request_id = fallback_request_id
        return self.search_response

    async def delete_document(self, payload, *, fallback_request_id: str):
        self.delete_payload = payload
        self.delete_fallback_request_id = fallback_request_id
        return self.delete_response


class _RetrievalSearchResult:
    chunks = [{"text": "answer"}]
    elapsed_ms = 5
    cache_hit = False


class _SearchRequest:
    def __init__(self, *, project_id: str, user_id: str, query: str) -> None:
        self.project_id = project_id
        self.user_id = user_id
        self.query = query


class _DeleteRequest:
    def __init__(self, *, project_id: str, user_id: str, kb_id: str, doc_id: str) -> None:
        self.project_id = project_id
        self.user_id = user_id
        self.kb_id = kb_id
        self.doc_id = doc_id


class _Config:
    project_id = "p1"
    collection_name = "rag_p1_v1"
    retrieval_config = {"top_k": 1, "candidate_count": 3}


class _SearchPlan:
    def __init__(self, *, request: _SearchRequest, config: _Config) -> None:
        self.request = request
        self.config = config
        self.retrieval_filter = object()


class _DeletePlan:
    def __init__(self, *, request: _DeleteRequest, config: _Config) -> None:
        self.request = request
        self.config = config


if __name__ == "__main__":
    unittest.main()
