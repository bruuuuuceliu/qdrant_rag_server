"""Manager service routing and project-task boundary tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import grpc

from configs.config import AppSettings
from configs.manager import load_manager_settings
from configs.manager import ManagerSettings
from manager_service import (
    DataType,
    ManagerRequestContext,
    ManagerRouter,
    Operation,
    RouteRequest,
    ServiceTarget,
)
from manager_service.service import ManagerService
from manager_service.service import ManagerTaskAccepted
from manager_service.server.grpc.server import ManagerRagServiceServicer
from shared.transport.grpc.generated import retrieval_service_pb2
from shared.contracts import JobStatus, MessageEnvelope, MessageType, TOPICS
from shared.contracts import TaskStatusRecord


class ManagerRouterTest(unittest.TestCase):
    def test_routes_project_document_ingest_to_task_manager(self) -> None:
        decision = ManagerRouter().route(
            RouteRequest(operation="ingest", data_type="project_document")
        )

        self.assertEqual(decision.operation, Operation.INGEST)
        self.assertEqual(decision.data_type, DataType.PROJECT_DOCUMENT)
        self.assertEqual(decision.target_service, ServiceTarget.TASK_MANAGER)
        self.assertTrue(decision.executable)

    def test_routes_project_document_search_to_task_manager(self) -> None:
        decision = ManagerRouter().route(
            RouteRequest(operation="search", data_type="project_document")
        )

        self.assertEqual(decision.target_service, ServiceTarget.TASK_MANAGER)
        self.assertTrue(decision.executable)

    def test_routes_project_document_status_to_task_status_store(self) -> None:
        decision = ManagerRouter().route(
            RouteRequest(operation="status", data_type="project_document")
        )

        self.assertEqual(decision.target_service, ServiceTarget.TASK_STATUS)
        self.assertTrue(decision.executable)

    def test_reserves_future_agent_memory_service(self) -> None:
        decision = ManagerRouter().route(
            RouteRequest(operation="search", data_type="agent_memory")
        )

        self.assertEqual(decision.target_service, ServiceTarget.MEMORY)
        self.assertFalse(decision.executable)
        self.assertTrue(decision.reserved)

    def test_reserves_future_workflow_log_service(self) -> None:
        decision = ManagerRouter().route(
            RouteRequest(operation="ingest", data_type="workflow_log")
        )

        self.assertEqual(decision.target_service, ServiceTarget.WORKFLOW_LOG)
        self.assertFalse(decision.executable)

    def test_rejects_unknown_data_type(self) -> None:
        with self.assertRaises(ValueError):
            ManagerRouter().route(RouteRequest(operation="search", data_type="unknown"))

    def test_rejects_unknown_operation(self) -> None:
        with self.assertRaises(ValueError):
            ManagerRouter().route(RouteRequest(operation="export", data_type="project_document"))


class ManagerSettingsTest(unittest.TestCase):
    def test_loads_manager_settings_from_values(self) -> None:
        settings = load_manager_settings(
            {
                "MANAGER_SERVICE_NAME": "edge",
                "MANAGER_TASK_INTAKE_TOPIC": "task.in",
            }
        )

        self.assertEqual(settings.service_name, "edge")
        self.assertEqual(settings.task_intake_topic, "task.in")


class ManagerServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_can_publish_ingest_task_intake_without_project_client(self) -> None:
        task_producer = _FakeTaskProducer()
        manager = ManagerService(task_producer=task_producer)
        request = {
            "project_id": "p1",
            "user_id": "u1",
            "kb_id": "kb",
            "doc_id": "d1",
            "metadata": {"data_type": "project_document"},
        }

        result = await manager.ingest(request)

        self.assertTrue(result.accepted)
        self.assertEqual(
            [published[0] for published in task_producer.published],
            [
                TOPICS.task_intake,
                TOPICS.manager_request_accepted,
                TOPICS.audit_events,
            ],
        )
        self.assertEqual(task_producer.published[0][0], TOPICS.task_intake)
        self.assertEqual(task_producer.published[0][2], result.task_id)
        envelope = task_producer.published[0][1]
        self.assertEqual(envelope.message_type, "request.accepted")
        self.assertEqual(envelope.data_type, "project_document")
        self.assertEqual(envelope.payload["operation"], "ingest")
        self.assertEqual(envelope.payload["request"]["project_id"], "p1")
        accepted = task_producer.published[1][1]
        self.assertEqual(accepted.message_type, MessageType.REQUEST_ACCEPTED)
        self.assertEqual(accepted.payload["status"], "accepted")
        self.assertEqual(accepted.payload["request"]["doc_id"], "d1")
        audit = task_producer.published[2][1]
        self.assertEqual(audit.message_type, MessageType.AUDIT_EVENT)
        self.assertEqual(audit.payload["event"], "manager.request.accepted")
        self.assertEqual(audit.payload["job_id"], result.task_id)
        self.assertEqual(audit.payload["project_id"], "p1")
        self.assertEqual(audit.payload["doc_id"], "d1")
        self.assertEqual(audit.payload["request"]["data_type"], "project_document")

    async def test_can_publish_search_task_intake_with_context(self) -> None:
        task_producer = _FakeTaskProducer()
        manager = ManagerService(task_producer=task_producer)
        request = _Request(metadata={"data_type": "project_document"})
        context = ManagerRequestContext(
            request_id="corr-1",
            auth_context={"subject_id": "user1"},
        )

        result = await manager.search(request, context=context)

        envelope = task_producer.published[0][1]
        self.assertEqual(result.correlation_id, "corr-1")
        self.assertEqual(envelope.correlation_id, "corr-1")
        self.assertEqual(envelope.payload["operation"], "search")
        self.assertEqual(envelope.payload["context"]["auth_context"]["subject_id"], "user1")

    async def test_can_publish_delete_task_intake(self) -> None:
        task_producer = _FakeTaskProducer()
        manager = ManagerService(task_producer=task_producer)
        request = _Request(metadata={"data_type": "project_document"})

        await manager.delete(request)

        envelope = task_producer.published[0][1]
        self.assertEqual(envelope.payload["operation"], "delete")

    async def test_broker_first_status_requires_status_store(self) -> None:
        manager = ManagerService(task_producer=_FakeTaskProducer())

        with self.assertRaisesRegex(ValueError, "status lookup"):
            await manager.ingest_status("task-1")

    async def test_status_reads_from_task_status_store_when_configured(self) -> None:
        status_store = _FakeTaskStatusStore()
        status_store.record = TaskStatusRecord(
            task_id="task-1",
            status="completed",
            operation="search",
        )
        manager = ManagerService(
            task_status_store=status_store,
            task_producer=_FakeTaskProducer(),
        )

        result = await manager.ingest_status("task-1")

        self.assertEqual(result, status_store.record)
        self.assertEqual(status_store.task_id, "task-1")

    async def test_rejects_reserved_future_route(self) -> None:
        manager = ManagerService(task_producer=_FakeTaskProducer())

        with self.assertRaises(ValueError):
            await manager.ingest(_Request(metadata={"data_type": "agent_memory"}))

    async def test_rejects_reserved_future_route_from_mapping_metadata(self) -> None:
        manager = ManagerService(task_producer=_FakeTaskProducer())

        with self.assertRaises(ValueError):
            await manager.ingest(
                {
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb",
                    "metadata": {"data_type": "agent_memory"},
                }
            )


class ManagerAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_manager_service_app_requires_injected_task_producer(self) -> None:
        from manager_service.server import app as manager_app

        with self.assertRaisesRegex(ValueError, "task producer"):
            await manager_app.create_app(_settings())

    async def test_manager_service_app_can_use_task_producer_without_project_client(self) -> None:
        from manager_service.server import app as manager_app

        task_producer = _FakeTaskProducer()
        task_status_store = _FakeTaskStatusStore()
        manager_server = _FakeServer()
        manager_settings = ManagerSettings(task_intake_topic="task.custom")

        with patch.object(
            manager_app,
            "serve_manager_grpc",
            AsyncMock(return_value=manager_server),
        ):
            context = await manager_app.create_app(
                _settings(),
                task_producer=task_producer,
                task_status_store=task_status_store,
                manager_settings=manager_settings,
            )

        result = await context.manager.search({"metadata": {"data_type": "project_document"}})

        self.assertEqual(task_producer.published[0][0], "task.custom")
        self.assertEqual(result.task_id, task_producer.published[0][2])
        await context.shutdown()
        manager_server.stop.assert_awaited_once_with(grace=5)

    async def test_manager_service_serve_forever_accepts_broker_first_dependencies(self) -> None:
        from manager_service.server import app as manager_app

        task_producer = _FakeTaskProducer()
        task_status_store = _FakeTaskStatusStore()
        manager_server = _FakeServer()

        with patch.object(
            manager_app,
            "serve_manager_grpc",
            AsyncMock(return_value=manager_server),
        ):
            await manager_app.serve_forever(
                _settings(),
                task_producer=task_producer,
                task_status_store=task_status_store,
                manager_settings=ManagerSettings(task_intake_topic="task.custom"),
            )

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

    async def test_search_waits_for_broker_first_task_result(self) -> None:
        manager = _FakeManager()
        manager.search_result = ManagerTaskAccepted(
            task_id="task-search",
            correlation_id="corr-search",
        )
        manager.status_result = TaskStatusRecord(
            task_id="task-search",
            status="completed",
            operation="search",
            result={
                "ok": True,
                "result": {
                    "chunks": [
                        {
                            "project_id": "p1",
                            "user_id": "u1",
                            "kb_id": "kb",
                            "doc_id": "d1",
                            "chunk_id": "chunk-from-task",
                            "chunk_index": 0,
                            "text": "task result",
                            "score": 0.9,
                        }
                    ],
                    "elapsed_ms": 11,
                    "cache_hit": False,
                },
            },
        )
        servicer = ManagerRagServiceServicer(manager=manager)

        response = await servicer.Search(
            retrieval_service_pb2.SearchRequest(
                project_id="p1",
                user_id="u1",
                query="hello",
                kb_ids=["kb"],
                include_shared=False,
            ),
            _FakeGrpcContext(),
        )

        self.assertEqual(response.chunks[0].chunk_id, "chunk-from-task")
        self.assertEqual(response.elapsed_ms, 11)
        self.assertEqual(manager.status_job_id, "task-search")

    async def test_search_maps_failed_broker_first_task_to_grpc_error(self) -> None:
        manager = _FakeManager()
        manager.search_result = ManagerTaskAccepted(
            task_id="task-search",
            correlation_id="corr-search",
        )
        manager.status_result = TaskStatusRecord(
            task_id="task-search",
            status="failed",
            operation="search",
            result={"error": "retrieval failed"},
        )
        context = _FakeGrpcContext()
        servicer = ManagerRagServiceServicer(manager=manager)

        with self.assertRaises(_GrpcAbort):
            await servicer.Search(
                retrieval_service_pb2.SearchRequest(
                    project_id="p1",
                    user_id="u1",
                    query="hello",
                ),
                context,
            )

        self.assertEqual(context.code, grpc.StatusCode.INTERNAL)
        self.assertEqual(context.details, "retrieval failed")

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

    async def test_ingest_maps_broker_first_task_acceptance_to_grpc_response(self) -> None:
        manager = _FakeManager()
        manager.ingest_result = ManagerTaskAccepted(
            task_id="task-1",
            correlation_id="corr-1",
        )
        servicer = ManagerRagServiceServicer(manager=manager)

        response = await servicer.Ingest(
            retrieval_service_pb2.IngestRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                source_uri="memory://d1",
                content_type="text/plain",
                metadata={"data_type": "project_document"},
            ),
            _FakeGrpcContext(),
        )

        self.assertEqual(response.job_id, "task-1")
        self.assertEqual(response.status, "accepted")

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

    async def test_get_ingest_status_maps_task_status_record_to_grpc_response(self) -> None:
        manager = _FakeManager()
        manager.status_result = TaskStatusRecord(
            task_id="task-1",
            status="completed",
            result={"doc_id": "doc-1"},
        )
        servicer = ManagerRagServiceServicer(manager=manager)

        response = await servicer.GetIngestJobStatus(
            retrieval_service_pb2.GetIngestJobStatusRequest(job_id="task-1"),
            _FakeGrpcContext(),
        )

        self.assertEqual(response.job_id, "task-1")
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.doc_id, "doc-1")

    async def test_get_ingest_status_extracts_doc_id_from_helper_results(self) -> None:
        manager = _FakeManager()
        manager.status_result = TaskStatusRecord(
            task_id="task-1",
            status="completed",
            result={
                "helpers": {
                    TOPICS.helper_ingestion_commands: {
                        "index_request": {
                            "chunks": [
                                {
                                    "document_id": "doc-from-chunk",
                                    "text": "hello",
                                }
                            ],
                        },
                    },
                },
            },
        )
        servicer = ManagerRagServiceServicer(manager=manager)

        response = await servicer.GetIngestJobStatus(
            retrieval_service_pb2.GetIngestJobStatusRequest(job_id="task-1"),
            _FakeGrpcContext(),
        )

        self.assertEqual(response.job_id, "task-1")
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.doc_id, "doc-from-chunk")

    async def test_get_ingest_status_maps_nested_task_error_to_grpc_response(self) -> None:
        manager = _FakeManager()
        manager.status_result = TaskStatusRecord(
            task_id="task-1",
            status="failed",
            result={"doc_id": "doc-1", "error": "source scheme is not allowed"},
        )
        servicer = ManagerRagServiceServicer(manager=manager)

        response = await servicer.GetIngestJobStatus(
            retrieval_service_pb2.GetIngestJobStatusRequest(job_id="task-1"),
            _FakeGrpcContext(),
        )

        self.assertEqual(response.job_id, "task-1")
        self.assertEqual(response.status, "failed")
        self.assertEqual(response.doc_id, "doc-1")
        self.assertEqual(response.error, "source scheme is not allowed")


class _Request:
    project_id = "p1"
    user_id = "u1"
    kb_id = "kb"

    def __init__(self, *, metadata: dict[str, object]) -> None:
        self.metadata = metadata


class _FakeTaskProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


class _FakeTaskStatusStore:
    def __init__(self) -> None:
        self.record: TaskStatusRecord | None = None
        self.task_id = ""

    async def set_status(self, record: TaskStatusRecord, *, ttl_seconds: int | None = None) -> None:
        self.record = record

    async def get_status(self, task_id: str) -> TaskStatusRecord | None:
        self.task_id = task_id
        return self.record


class _FakeServer:
    def __init__(self) -> None:
        self.stop = AsyncMock()

    async def wait_for_termination(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class _SearchResult:
    chunks: list[dict[str, object]]
    elapsed_ms: int
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class _IngestResult:
    job_id: str
    status: JobStatus
    doc_id: str = ""
    error: str | None = None


class _FakeManager:
    search_request: object | None = None
    ingest_request: object | None = None
    status_job_id: str | None = None
    ingest_error: Exception | None = None
    ingest_result: object | None = None
    search_result: object | None = None
    status_result: object | None = None

    async def search(self, request: object) -> _SearchResult:
        self.search_request = request
        if self.search_result is not None:
            return self.search_result
        return _SearchResult(
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

    async def ingest(self, request: object) -> _IngestResult:
        self.ingest_request = request
        if self.ingest_error is not None:
            raise self.ingest_error
        if self.ingest_result is not None:
            return self.ingest_result
        return _IngestResult(
            job_id="job1",
            status=JobStatus.PENDING,
            doc_id="d1",
        )

    async def ingest_status(self, job_id: str) -> _IngestResult:
        self.status_job_id = job_id
        if self.status_result is not None:
            return self.status_result
        return _IngestResult(
            job_id=job_id,
            status=JobStatus.PENDING,
            doc_id="d1",
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

    def time_remaining(self) -> float:
        return 10.0


def _settings() -> AppSettings:
    return AppSettings(
        response_cache_db_path=Path("/tmp/test-cache.db"),
        grpc_port=0,
        qdrant_url=None,
        qdrant_host="localhost",
        qdrant_port=6333,
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
