"""Manager service routing and local queue tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import grpc

from configs.config import AppSettings
from configs.manager import load_manager_settings
from configs.manager import ManagerSettings
from manager_service import (
    DataType,
    ManagerIngestFailedError,
    ManagerRouter,
    Operation,
    ProjectDocumentClient,
    RouteRequest,
    ServiceTarget,
)
from manager_service.service import ManagerService
from manager_service.server.grpc.server import ManagerRagServiceServicer
from project_service.schemas import IngestResult, SearchResult
from project_service.server.grpc.generated import retrieval_service_pb2
from retrieval_service.core.schemas import JobStatus
from shared.queue import LocalQueueBroker, QueueFullError, QueueMessage
from ingestion_service.server import create_app as create_ingestion_app


class ManagerRouterTest(unittest.TestCase):
    def test_routes_project_document_ingest_to_ingestion_queue(self) -> None:
        decision = ManagerRouter(ingest_topic="docs.ingest").route(
            RouteRequest(operation="ingest", data_type="project_document")
        )

        self.assertEqual(decision.operation, Operation.INGEST)
        self.assertEqual(decision.data_type, DataType.PROJECT_DOCUMENT)
        self.assertEqual(decision.target_service, ServiceTarget.INGESTION)
        self.assertTrue(decision.executable)
        self.assertTrue(decision.async_required)
        self.assertEqual(decision.queue_topic, "docs.ingest")

    def test_routes_project_document_search_to_retrieval(self) -> None:
        decision = ManagerRouter().route(
            RouteRequest(operation="search", data_type="project_document")
        )

        self.assertEqual(decision.target_service, ServiceTarget.RETRIEVAL)
        self.assertTrue(decision.executable)
        self.assertFalse(decision.async_required)

    def test_reserves_future_agent_memory_service(self) -> None:
        decision = ManagerRouter().route(
            RouteRequest(operation="search", data_type="agent_memory")
        )

        self.assertEqual(decision.target_service, ServiceTarget.MEMORY)
        self.assertFalse(decision.executable)
        self.assertTrue(decision.reserved)

    def test_reserves_future_workflow_log_topic(self) -> None:
        decision = ManagerRouter(workflow_topic="logs.events").route(
            RouteRequest(operation="ingest", data_type="workflow_log")
        )

        self.assertEqual(decision.target_service, ServiceTarget.WORKFLOW_LOG)
        self.assertEqual(decision.queue_topic, "logs.events")
        self.assertFalse(decision.executable)
        self.assertTrue(decision.async_required)

    def test_rejects_unknown_data_type(self) -> None:
        with self.assertRaises(ValueError):
            ManagerRouter().route(RouteRequest(operation="search", data_type="unknown"))

    def test_rejects_unknown_operation(self) -> None:
        with self.assertRaises(ValueError):
            ManagerRouter().route(RouteRequest(operation="export", data_type="project_document"))


class LocalQueueBrokerTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_and_consume_message(self) -> None:
        broker = LocalQueueBroker(maxsize=1)
        message = QueueMessage(
            topic="ingestion.requests",
            key="p1:d1",
            payload={"doc_id": "d1"},
            headers={"correlation_id": "c1"},
        )

        await broker.publish(message)
        self.assertEqual(broker.depth("ingestion.requests"), 1)
        consumed = await broker.consume("ingestion.requests")

        self.assertEqual(consumed, message)
        broker.task_done("ingestion.requests")
        await broker.join("ingestion.requests")

    async def test_publish_raises_when_topic_queue_is_full(self) -> None:
        broker = LocalQueueBroker(maxsize=1)
        await broker.publish(QueueMessage(topic="t", key="1", payload={}))

        with self.assertRaises(QueueFullError):
            await broker.publish(QueueMessage(topic="t", key="2", payload={}))


class ManagerSettingsTest(unittest.TestCase):
    def test_loads_manager_settings_from_values(self) -> None:
        settings = load_manager_settings(
            {
                "MANAGER_SERVICE_NAME": "edge",
                "MANAGER_INGEST_TOPIC": "docs.in",
                "MANAGER_WORKFLOW_TOPIC": "logs.in",
                "MANAGER_LOCAL_QUEUE_MAXSIZE": "25",
            }
        )

        self.assertEqual(settings.service_name, "edge")
        self.assertEqual(settings.ingest_topic, "docs.in")
        self.assertEqual(settings.workflow_topic, "logs.in")
        self.assertEqual(settings.local_queue_maxsize, 25)


class ManagerServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_delegates_executable_project_document_route(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(
            project_documents=project_client,
        )
        request = _Request(metadata={"data_type": "project_document"})

        result = await manager.ingest(request)

        self.assertEqual(result.job_id, "job1")
        self.assertEqual(result.status, JobStatus.PENDING)
        self.assertIs(project_client.ingest_request, request)

    async def test_search_delegates_through_project_and_retrieval_clients(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(
            project_documents=project_client,
        )
        request = _Request(metadata={"data_type": "project_document"})

        result = await manager.search(request)

        self.assertEqual(result, "search-result")
        self.assertIs(project_client.search_request, request)

    async def test_status_delegates_to_ingestion_client(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(
            project_documents=project_client,
        )

        result = await manager.ingest_status("job1")

        self.assertEqual(result, "status:job1")
        self.assertEqual(project_client.status_job_id, "job1")

    async def test_status_rejects_reserved_future_route(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(project_documents=project_client)

        with self.assertRaises(ValueError):
            await manager.ingest_status("job1", data_type="workflow_log")

        self.assertIsNone(project_client.status_job_id)

    async def test_delete_delegates_executable_project_document_route(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(project_documents=project_client)
        request = _Request(metadata={"data_type": "project_document"})

        result = await manager.delete(request)

        self.assertEqual(result, "deleted")
        self.assertIs(project_client.delete_request, request)

    async def test_rejects_reserved_future_route(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(
            project_documents=project_client,
        )

        with self.assertRaises(ValueError):
            await manager.ingest(_Request(metadata={"data_type": "agent_memory"}))

        self.assertIsNone(project_client.ingest_request)

    async def test_rejects_reserved_future_route_from_mapping_metadata(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(project_documents=project_client)

        with self.assertRaises(ValueError):
            await manager.ingest(
                {
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "metadata": {"data_type": "agent_memory"},
                }
            )

        self.assertIsNone(project_client.ingest_request)

    async def test_ingest_can_route_through_request_queue(self) -> None:
        broker = LocalQueueBroker()
        project_client = _FakeProjectDocumentClient()
        ingestion_app = await create_ingestion_app(
            queue=broker,
            project_documents=project_client,
            enabled=True,
            topic="ingestion.requests",
        )
        manager = ManagerService(
            project_documents=project_client,
            ingest_queue=broker,
            ingest_topic="ingestion.requests",
            ingest_response_timeout=1,
        )

        result = await manager.ingest(
            {
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
                "source_uri": "memory://d1",
                "content_type": "text/plain",
                "metadata": {"data_type": "project_document"},
            }
        )

        self.assertIsInstance(result, IngestResult)
        self.assertEqual(result.job_id, "job1")
        self.assertEqual(result.status, JobStatus.PENDING)
        self.assertEqual(project_client.ingest_request["doc_id"], "d1")

        await ingestion_app.shutdown()

    async def test_ingest_queue_failure_raises_manager_error(self) -> None:
        queue = _FailingIngestQueue()
        manager = ManagerService(
            project_documents=_FakeProjectDocumentClient(),
            ingest_queue=queue,
            ingest_topic="ingestion.requests",
            ingest_response_timeout=1,
        )

        with self.assertRaises(ManagerIngestFailedError) as raised:
            await manager.ingest(_Request(metadata={"data_type": "project_document"}))

        self.assertEqual(str(raised.exception), "bad input")
        self.assertEqual(queue.published.topic, "ingestion.requests")


class ManagerAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_app_uses_manager_settings_for_router_topics(self) -> None:
        from manager_service.server import app as manager_app

        project_app = _FakeProjectApp()
        manager_server = _FakeServer()
        manager_settings = ManagerSettings(
            ingest_topic="custom.ingest",
            workflow_topic="custom.workflow",
        )

        with patch.object(
            manager_app,
            "create_project_app",
            AsyncMock(return_value=project_app),
        ) as create_project_app, patch.object(
            manager_app,
            "serve_manager_grpc",
            AsyncMock(return_value=manager_server),
        ) as serve_manager_grpc:
            context = await manager_app.create_app(
                _settings(),
                manager_settings=manager_settings,
            )

        decision = context.manager._router.route(
            RouteRequest(operation="ingest", data_type="project_document")
        )
        self.assertEqual(decision.queue_topic, "custom.ingest")
        self.assertEqual(context.ingestion_app.topic, "custom.ingest")
        self.assertEqual(context.manager_settings.workflow_topic, "custom.workflow")
        self.assertIs(context.server, manager_server)
        create_project_app.assert_awaited_once_with(_settings(), start_server=False)
        serve_manager_grpc.assert_awaited_once()
        self.assertIs(serve_manager_grpc.await_args.kwargs["health_checker"], project_app.health_checker)
        await context.shutdown()
        manager_server.stop.assert_awaited_once_with(grace=5)


class ManagerGrpcServicerTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_routes_through_manager(self) -> None:
        manager = _FakeManager()
        servicer = ManagerRagServiceServicer(manager=manager)

        response = await servicer.Search(
            retrieval_service_pb2.SearchRequest(
                project_id="p1",
                user_id="u1",
                query="hello",
                kb_ids=["kb1"],
                include_shared=False,
            ),
            _FakeGrpcContext(),
        )

        self.assertEqual(response.chunks[0].chunk_id, "chunk1")
        self.assertEqual(response.elapsed_ms, 7)
        self.assertFalse(response.cache_hit)
        self.assertEqual(manager.search_request.project_id, "p1")
        self.assertEqual(manager.search_request.kb_ids, ("kb1",))

    async def test_ingest_routes_through_manager(self) -> None:
        manager = _FakeManager()
        servicer = ManagerRagServiceServicer(manager=manager)

        response = await servicer.Ingest(
            retrieval_service_pb2.IngestRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                source_uri="file:///tmp/doc.pdf",
                content_type="application/pdf",
                metadata={"data_type": "project_document"},
            ),
            _FakeGrpcContext(),
        )

        self.assertEqual(response.job_id, "job1")
        self.assertEqual(response.status, JobStatus.PENDING.value)
        self.assertEqual(manager.ingest_request.source_uri, "file:///tmp/doc.pdf")
        self.assertEqual(manager.ingest_request.metadata["data_type"], "project_document")

    async def test_ingest_queue_full_maps_to_resource_exhausted(self) -> None:
        manager = _FakeManager()
        manager.ingest_error = QueueFullError("queue is full")
        servicer = ManagerRagServiceServicer(manager=manager)
        context = _FakeGrpcContext()

        with self.assertRaises(_GrpcAbort):
            await servicer.Ingest(
                retrieval_service_pb2.IngestRequest(
                    project_id="p1",
                    user_id="u1",
                    kb_id="kb",
                    doc_id="d1",
                    source_uri="file:///tmp/doc.pdf",
                    content_type="application/pdf",
                ),
                context,
            )

        self.assertEqual(context.code, grpc.StatusCode.RESOURCE_EXHAUSTED)

    async def test_get_ingest_status_routes_through_manager(self) -> None:
        manager = _FakeManager()
        servicer = ManagerRagServiceServicer(manager=manager)

        response = await servicer.GetIngestJobStatus(
            retrieval_service_pb2.GetIngestJobStatusRequest(job_id="job1"),
            _FakeGrpcContext(),
        )

        self.assertEqual(response.job_id, "job1")
        self.assertEqual(response.status, JobStatus.PENDING.value)
        self.assertEqual(response.doc_id, "d1")
        self.assertEqual(manager.status_job_id, "job1")


class _Request:
    project_id = "p1"
    user_id = "u1"
    kb_id = "kb"

    def __init__(self, *, metadata: dict[str, object]) -> None:
        self.metadata = metadata


class _FakeGateway:
    ingest_request: object | None = None
    search_request: object | None = None

    async def prepare_ingest(self, request: object) -> str:
        self.ingest_request = request
        return "ingest-plan"

    async def prepare_search(self, request: object) -> str:
        self.search_request = request
        return "search-plan"


class _FakeEngine:
    ingest_plan: object | None = None
    search_plan: object | None = None

    async def schedule_ingest(self, plan: object) -> str:
        self.ingest_plan = plan
        return "scheduled"

    async def search(self, plan: object) -> str:
        self.search_plan = plan
        return "search-result"

    async def get_ingest_status(self, job_id: str) -> str:
        return f"status:{job_id}"


class _FakeProjectDocumentClient:
    ingest_request: object | None = None
    search_request: object | None = None
    status_job_id: str | None = None
    delete_request: object | None = None

    async def ingest(self, request: object) -> str:
        self.ingest_request = request
        return IngestResult(
            job_id="job1",
            status=JobStatus.PENDING,
            doc_id="d1",
            project_id="p1",
            user_id="u1",
            kb_id="kb",
        )

    async def search(self, request: object) -> str:
        self.search_request = request
        return "search-result"

    async def ingest_status(self, job_id: str) -> str:
        self.status_job_id = job_id
        return f"status:{job_id}"

    async def delete_document(self, request: object) -> str:
        self.delete_request = request
        return "deleted"


class _FakeProjectApp:
    gateway = _FakeGateway()
    engine = _FakeEngine()
    project_client: ProjectDocumentClient = _FakeProjectDocumentClient()
    server = object()

    def __init__(self) -> None:
        self.settings = _settings()
        self.health_checker = _FakeHealthChecker()

    async def shutdown(self) -> None:
        return None


class _FakeHealthChecker:
    async def check(self) -> SimpleNamespace:
        return SimpleNamespace(status="healthy", components=[])


class _FakeServer:
    def __init__(self) -> None:
        self.stop = AsyncMock()

    async def wait_for_termination(self) -> None:
        return None


class _FakeManager:
    search_request: object | None = None
    ingest_request: object | None = None
    status_job_id: str | None = None
    ingest_error: Exception | None = None

    async def search(self, request: object) -> SearchResult:
        self.search_request = request
        return SearchResult(
            chunks=[
                {
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "doc_id": "d1",
                    "chunk_id": "chunk1",
                    "chunk_index": 0,
                    "text": "hello world",
                    "score": 0.5,
                }
            ],
            elapsed_ms=7,
            cache_hit=False,
        )

    async def ingest(self, request: object) -> IngestResult:
        self.ingest_request = request
        if self.ingest_error is not None:
            raise self.ingest_error
        return IngestResult(
            job_id="job1",
            status=JobStatus.PENDING,
            doc_id="d1",
            project_id="p1",
            user_id="u1",
            kb_id="kb",
        )

    async def ingest_status(self, job_id: str) -> IngestResult:
        self.status_job_id = job_id
        return IngestResult(
            job_id=job_id,
            status=JobStatus.PENDING,
            doc_id="d1",
            project_id="p1",
            user_id="u1",
            kb_id="kb",
        )


class _GrpcAbort(Exception):
    pass


class _FakeGrpcContext:
    code: grpc.StatusCode | None = None
    details: str | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.code = code
        self.details = details
        raise _GrpcAbort(details)


class _FailingIngestQueue:
    published: QueueMessage

    async def publish(self, message: QueueMessage) -> None:
        self.published = message

    async def consume(self, topic: str) -> QueueMessage:
        return QueueMessage(
            topic=topic,
            key=self.published.key,
            payload={
                "request_id": self.published.key,
                "ok": False,
                "error": "bad input",
            },
        )

    def task_done(self, topic: str) -> None:
        return None


def _settings() -> AppSettings:
    return AppSettings(
        config_db_path=Path("/tmp/test-config.db"),
        response_cache_db_path=Path("/tmp/test-cache.db"),
        grpc_port=0,
        qdrant_url=None,
        qdrant_host="localhost",
        qdrant_port=6333,
        max_per_project=1,
        max_per_user=1,
        ingest_worker_count=1,
        embedding_provider="local",
        embedding_model="test",
        embedding_device="cpu",
        embedding_api_key="",
        embedding_base_url="",
        embedding_dimension=3,
        generation_enabled=False,
    )


if __name__ == "__main__":
    unittest.main()
