"""Manager service routing and project-task boundary tests."""

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
    IngestionApiStatusClient,
    LocalIngestionClient,
    LocalRetrievalClient,
    ManagerRequestContext,
    ManagerRouter,
    Operation,
    ProjectDocumentClient,
    RouteRequest,
    ServiceTarget,
)
from manager_service.service import ManagerService
from manager_service.server.grpc.server import ManagerRagServiceServicer
from ingestion_service.schemas import IngestionJob
from project_service.schemas import IngestResult, SearchResult
from project_service.server.grpc.generated import retrieval_service_pb2
from retrieval_service.core.schemas import JobStatus
from shared.queue import LocalQueueBroker, QueueFullError, QueueMessage


class ManagerRouterTest(unittest.TestCase):
    def test_routes_project_document_ingest_to_project_service(self) -> None:
        decision = ManagerRouter(ingest_topic="docs.ingest").route(
            RouteRequest(operation="ingest", data_type="project_document")
        )

        self.assertEqual(decision.operation, Operation.INGEST)
        self.assertEqual(decision.data_type, DataType.PROJECT_DOCUMENT)
        self.assertEqual(decision.target_service, ServiceTarget.PROJECT)
        self.assertTrue(decision.executable)
        self.assertTrue(decision.async_required)
        self.assertEqual(decision.queue_topic, "")

    def test_routes_project_document_search_to_project_service(self) -> None:
        decision = ManagerRouter().route(
            RouteRequest(operation="search", data_type="project_document")
        )

        self.assertEqual(decision.target_service, ServiceTarget.PROJECT)
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
    async def test_requires_project_document_client(self) -> None:
        with self.assertRaisesRegex(ValueError, "project-document client"):
            ManagerService(project_documents=None)

    async def test_can_use_local_retrieval_client_adapter(self) -> None:
        ingestion_client = _FakeIngestionClient()
        retrieval_app = _FakeRetrievalApp()
        client = LocalRetrievalClient(retrieval_app)
        request = _Request(metadata={"data_type": "project_document"})

        search_result = await client.search(request)
        delete_result = await client.delete_document(request)

        self.assertEqual(search_result, "retrieval-search")
        self.assertEqual(delete_result, "retrieval-delete")
        self.assertIs(retrieval_app.search_request, request)
        self.assertIs(retrieval_app.delete_request, request)

    async def test_can_use_local_ingestion_client_adapter(self) -> None:
        ingestion_executor = _FakeIngestionExecutor()
        jobs = _FakeIngestionJobs()
        jobs.record = IngestionJob(
            job_id="job1",
            source_uri="memory://d1",
            document_id="d1",
            status=JobStatus.RUNNING,
            metadata={"project_id": "p1", "doc_id": "d1"},
        )
        client = LocalIngestionClient(ingestion=ingestion_executor, jobs=jobs)
        request = _Request(metadata={"data_type": "project_document"})

        ingest_result = await client.ingest(request)
        status_result = await client.ingest_status("job1")

        self.assertEqual(ingest_result, "accepted")
        self.assertIs(ingestion_executor.ingest_request, request)
        self.assertEqual(status_result.job_id, "job1")
        self.assertEqual(status_result.status, JobStatus.RUNNING)
        self.assertEqual(status_result.doc_id, "d1")
        self.assertEqual(status_result.project_id, "p1")

    async def test_can_use_ingestion_api_status_client_adapter(self) -> None:
        ingestion_executor = _FakeIngestionExecutor()
        api = _FakeIngestionApi()
        client = IngestionApiStatusClient(
            ingestion=ingestion_executor,
            api=api,
        )
        request = _Request(metadata={"data_type": "project_document"})

        ingest_result = await client.ingest(request)
        status_result = await client.ingest_status("job1")

        self.assertEqual(ingest_result, "accepted")
        self.assertIs(ingestion_executor.ingest_request, request)
        self.assertEqual(status_result.job_id, "job1")
        self.assertEqual(status_result.status, JobStatus.COMPLETED)
        self.assertEqual(status_result.doc_id, "d1")
        self.assertEqual(status_result.project_id, "p1")
        self.assertEqual(api.status_payload["request"]["job_id"], "job1")

    async def test_ingestion_api_status_client_preserves_missing_job_fallback(self) -> None:
        api = _FakeIngestionApi(ok=False, code="not_found")
        client = IngestionApiStatusClient(
            ingestion=_FakeIngestionExecutor(),
            api=api,
        )

        result = await client.ingest_status("missing")

        self.assertEqual(result.job_id, "missing")
        self.assertEqual(result.status, JobStatus.PENDING)

    async def test_ingestion_api_status_client_raises_other_api_failures(self) -> None:
        api = _FakeIngestionApi(ok=False, code="unavailable", message="down")
        client = IngestionApiStatusClient(
            ingestion=_FakeIngestionExecutor(),
            api=api,
        )

        with self.assertRaisesRegex(RuntimeError, "unavailable: down"):
            await client.ingest_status("job1")

    async def test_ingest_delegates_to_project_document_task_start(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(
            project_documents=project_client,
        )
        request = _Request(metadata={"data_type": "project_document"})

        result = await manager.ingest(request)

        self.assertEqual(result.job_id, "job1")
        self.assertEqual(result.status, JobStatus.PENDING)
        self.assertIs(project_client.ingest_request, request)
        self.assertEqual(project_client.started_task_request, request)

    async def test_search_delegates_to_project_document_task_executor(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(
            project_documents=project_client,
        )
        request = _Request(metadata={"data_type": "project_document"})

        result = await manager.search(request)

        self.assertEqual(result, "search-result")
        self.assertIs(project_client.search_request, request)
        self.assertEqual(project_client.searched_documents_request, request)

    async def test_status_delegates_to_project_document_task_status(self) -> None:
        project_client = _FakeProjectDocumentClient()
        manager = ManagerService(
            project_documents=project_client,
        )

        result = await manager.ingest_status("job1")

        self.assertEqual(result, "status:job1")
        self.assertEqual(project_client.status_job_id, "job1")
        self.assertEqual(project_client.task_status_job_id, "job1")

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

    async def test_forwards_manager_request_context_to_project_tasks(self) -> None:
        project_client = _ContextAwareProjectDocumentClient()
        manager = ManagerService(project_documents=project_client)
        request = _Request(metadata={"data_type": "project_document"})
        context = ManagerRequestContext(
            request_id="req1",
            auth_context={"subject_id": "user1", "customer_id": "cust1"},
            customer_context={"customer_tier": "premium"},
            placement_hint={"routing_key_hint": "project:p1"},
        )

        await manager.ingest(request, context=context)
        await manager.search(request, context=context)
        await manager.ingest_status("job1", context=context)
        await manager.delete(request, context=context)

        self.assertEqual(project_client.contexts[0]["request_id"], "req1")
        self.assertEqual(project_client.contexts[0]["auth_context"]["customer_id"], "cust1")
        self.assertEqual(project_client.contexts[1]["customer_context"]["customer_tier"], "premium")
        self.assertEqual(
            project_client.contexts[2]["placement_hint"]["routing_key_hint"],
            "project:p1",
        )
        self.assertEqual(len(project_client.contexts), 4)

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


class ManagerAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_manager_service_app_requires_injected_project_client(self) -> None:
        from manager_service.server import app as manager_app

        with self.assertRaisesRegex(ValueError, "project-document client"):
            await manager_app.create_app(_settings())

    async def test_manager_service_app_uses_injected_project_client(self) -> None:
        from manager_service.server import app as manager_app

        project_client = _FakeProjectDocumentClient()
        manager_server = _FakeServer()
        manager_settings = ManagerSettings(
            ingest_topic="custom.ingest",
            workflow_topic="custom.workflow",
        )

        with patch.object(
            manager_app,
            "serve_manager_grpc",
            AsyncMock(return_value=manager_server),
        ) as serve_manager_grpc:
            context = await manager_app.create_app(
                _settings(),
                project_client=project_client,
                manager_settings=manager_settings,
            )

        decision = context.manager._router.route(
            RouteRequest(operation="ingest", data_type="project_document")
        )
        self.assertEqual(decision.queue_topic, "")
        self.assertEqual(decision.target_service, ServiceTarget.PROJECT)
        self.assertIs(context.manager._project_documents, project_client)
        self.assertIs(context.project_client, project_client)
        self.assertEqual(context.manager_settings.workflow_topic, "custom.workflow")
        self.assertIs(context.server, manager_server)
        serve_manager_grpc.assert_awaited_once()
        self.assertIsNone(serve_manager_grpc.await_args.kwargs["health_checker"])
        self.assertIsNone(serve_manager_grpc.await_args.kwargs["generation_engine"])
        await context.shutdown()
        manager_server.stop.assert_awaited_once_with(grace=5)

    async def test_create_app_uses_manager_settings_for_router_topics(self) -> None:
        from local_runtime import manager_app

        project_app = _FakeProjectApp()
        ingestion_app = _FakeIngestionApp()
        retrieval_api_app = _FakeRetrievalApiApp()
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
            "create_ingestion_app",
            AsyncMock(return_value=ingestion_app),
        ) as create_ingestion_app, patch.object(
            manager_app,
            "create_ingestion_api_app",
            AsyncMock(),
        ) as create_ingestion_api_app, patch.object(
            manager_app,
            "create_retrieval_api_app",
            AsyncMock(return_value=retrieval_api_app),
        ) as create_retrieval_api_app, patch.object(
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
        self.assertEqual(decision.queue_topic, "")
        self.assertEqual(decision.target_service, ServiceTarget.PROJECT)
        self.assertEqual(context.ingestion_app.topic, "custom.ingest")
        self.assertIs(context.ingestion_jobs, context.ingestion_app.jobs)
        self.assertIs(context.ingestion_api_app, create_ingestion_api_app.return_value)
        self.assertEqual(context.manager_settings.workflow_topic, "custom.workflow")
        self.assertIs(context.server, manager_server)
        self.assertIs(context.retrieval_api_app, retrieval_api_app)
        self.assertIsNot(context.manager._project_documents, project_app.project_client)
        create_project_app.assert_awaited_once_with(_settings(), start_server=False)
        create_ingestion_app.assert_awaited_once()
        self.assertIs(create_ingestion_app.await_args.kwargs["retrieval_queue"], create_ingestion_app.await_args.kwargs["queue"])
        self.assertNotIn("project_documents", create_ingestion_app.await_args.kwargs)
        create_ingestion_api_app.assert_awaited_once_with(
            ingestion_app=ingestion_app,
        )
        create_retrieval_api_app.assert_awaited_once_with(
            retrieval_service=project_app.engine.retrieval_service,
        )
        serve_manager_grpc.assert_awaited_once()
        self.assertIs(serve_manager_grpc.await_args.kwargs["health_checker"], project_app.health_checker)
        await context.shutdown()
        manager_server.stop.assert_awaited_once_with(grace=5)
        create_ingestion_api_app.return_value.shutdown.assert_awaited_once()
        ingestion_app.shutdown.assert_not_awaited()
        retrieval_api_app.shutdown.assert_awaited_once()

    async def test_create_app_external_ingestion_mode_skips_embedded_consumer(self) -> None:
        from local_runtime import manager_app

        project_app = _FakeProjectApp()
        manager_server = _FakeServer()
        manager_settings = ManagerSettings(
            ingest_topic="custom.ingest",
            ingestion_worker_mode="external",
            queue_broker="sqlite",
            queue_db_path=":memory:",
        )

        with patch.object(
            manager_app,
            "create_project_app",
            AsyncMock(return_value=project_app),
        ), patch.object(
            manager_app,
            "create_ingestion_app",
            AsyncMock(),
        ) as create_ingestion_app, patch.object(
            manager_app,
            "serve_manager_grpc",
            AsyncMock(return_value=manager_server),
        ):
            context = await manager_app.create_app(
                _settings(),
                manager_settings=manager_settings,
            )

        self.assertIsNone(context.ingestion_app)
        self.assertIsNone(context.ingestion_api_app)
        self.assertIsNone(context.ingestion_jobs)
        create_ingestion_app.assert_not_called()
        self.assertEqual(context.manager._ingest_topic, "custom.ingest")
        await context.shutdown()

    async def test_create_app_queue_retrieval_mode_uses_retrieval_queue_client(self) -> None:
        from local_runtime import manager_app

        project_app = _FakeProjectApp()
        retrieval_queue_app = _FakeRetrievalApiApp()
        retrieval_queue_client = _FakeRetrievalQueueClient()
        manager_server = _FakeServer()
        manager_settings = ManagerSettings(
            retrieval_client_mode="queue",
            retrieval_topic="retrieval.custom",
            retrieval_response_timeout=2.5,
        )

        with patch.object(
            manager_app,
            "create_project_app",
            AsyncMock(return_value=project_app),
        ), patch.object(
            manager_app,
            "create_retrieval_queue_app",
            AsyncMock(return_value=retrieval_queue_app),
        ) as create_retrieval_queue_app, patch.object(
            manager_app,
            "RetrievalApiQueueClient",
            return_value=retrieval_queue_client,
        ) as retrieval_queue_client_class, patch.object(
            manager_app,
            "serve_manager_grpc",
            AsyncMock(return_value=manager_server),
        ):
            context = await manager_app.create_app(
                _settings(),
                manager_settings=manager_settings,
            )

        self.assertIs(context.retrieval_api_app, retrieval_queue_app)
        self.assertIsNot(context.manager._project_documents, project_app.project_client)
        create_retrieval_queue_app.assert_awaited_once()
        self.assertEqual(create_retrieval_queue_app.await_args.kwargs["topic"], "retrieval.custom")
        retrieval_queue_client_class.assert_called_once()
        self.assertEqual(retrieval_queue_client_class.call_args.kwargs["topic"], "retrieval.custom")
        self.assertEqual(
            retrieval_queue_client_class.call_args.kwargs["response_timeout"],
            2.5,
        )
        await context.shutdown()
        retrieval_queue_app.shutdown.assert_awaited_once()

    async def test_create_app_http_retrieval_mode_uses_remote_http_client(self) -> None:
        from local_runtime import manager_app

        project_app = _FakeProjectApp()
        retrieval_http_client = _FakeRetrievalHttpClient()
        manager_server = _FakeServer()
        manager_settings = ManagerSettings(
            retrieval_client_mode="http",
            retrieval_http_base_url="http://retrieval:8081",
            retrieval_http_timeout=4.5,
        )

        with patch.object(
            manager_app,
            "create_project_app",
            AsyncMock(return_value=project_app),
        ), patch.object(
            manager_app,
            "create_retrieval_api_app",
            AsyncMock(),
        ) as create_retrieval_api_app, patch.object(
            manager_app,
            "create_retrieval_queue_app",
            AsyncMock(),
        ) as create_retrieval_queue_app, patch.object(
            manager_app,
            "RetrievalApiHttpClient",
            return_value=retrieval_http_client,
        ) as retrieval_http_client_class, patch.object(
            manager_app,
            "serve_manager_grpc",
            AsyncMock(return_value=manager_server),
        ):
            context = await manager_app.create_app(
                _settings(),
                manager_settings=manager_settings,
            )

        self.assertIsNone(context.retrieval_api_app)
        self.assertIs(context.retrieval_api_client, retrieval_http_client)
        self.assertIsNot(context.manager._project_documents, project_app.project_client)
        create_retrieval_api_app.assert_not_called()
        create_retrieval_queue_app.assert_not_called()
        retrieval_http_client_class.assert_called_once_with(
            base_url="http://retrieval:8081",
            timeout=4.5,
        )
        await context.shutdown()
        retrieval_http_client.shutdown.assert_awaited_once()

    async def test_create_app_rejects_unknown_retrieval_client_mode(self) -> None:
        from local_runtime import manager_app

        manager_settings = ManagerSettings(retrieval_client_mode="bad")

        with patch.object(
            manager_app,
            "create_project_app",
            AsyncMock(return_value=_FakeProjectApp()),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "MANAGER_RETRIEVAL_CLIENT_MODE",
            ):
                await manager_app.create_app(
                    _settings(),
                    manager_settings=manager_settings,
                )

    async def test_create_app_grpc_project_mode_uses_remote_client(self) -> None:
        from local_runtime import manager_app

        manager_server = _FakeServer()
        remote_client = _FakeRemoteProjectClient()
        manager_settings = ManagerSettings(
            project_client_mode="grpc",
            project_grpc_target="localhost:50052",
            ingestion_worker_mode="external",
        )

        with patch.object(
            manager_app,
            "create_project_app",
            AsyncMock(),
        ) as create_project_app, patch.object(
            manager_app,
            "RemoteProjectServiceClient",
            return_value=remote_client,
        ) as remote_client_class, patch.object(
            manager_app,
            "serve_manager_grpc",
            AsyncMock(return_value=manager_server),
        ) as serve_manager_grpc:
            context = await manager_app.create_app(
                _settings(),
                manager_settings=manager_settings,
            )

        create_project_app.assert_not_called()
        remote_client_class.assert_called_once_with(target="localhost:50052")
        self.assertIs(context.project_app, None)
        self.assertIs(context.project_client, remote_client)
        self.assertIs(context.manager._project_documents, remote_client)
        self.assertIsNone(serve_manager_grpc.await_args.kwargs["health_checker"])
        self.assertIsNone(serve_manager_grpc.await_args.kwargs["generation_engine"])

        await context.shutdown()
        remote_client.shutdown.assert_awaited_once()


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
    retrieval_service = object()

    async def schedule_ingest(self, plan: object) -> str:
        self.ingest_plan = plan
        return "scheduled"

    async def search(self, plan: object) -> str:
        self.search_plan = plan
        return "search-result"

    async def get_ingest_status(self, job_id: str) -> str:
        return f"status:{job_id}"


class _FakeRetrievalApiApp:
    def __init__(self) -> None:
        self.shutdown = AsyncMock()


class _FakeRetrievalQueueClient:
    async def search(self, payload):
        return {"request_id": "req", "ok": True, "result": {"chunks": []}}

    async def delete_document(self, payload):
        return {"request_id": "req", "ok": True, "result": {"deleted": True}}


class _FakeRetrievalHttpClient:
    def __init__(self) -> None:
        self.shutdown = AsyncMock()

    async def search(self, payload):
        return {"request_id": "req", "ok": True, "result": {"chunks": []}}

    async def delete_document(self, payload):
        return {"request_id": "req", "ok": True, "result": {"deleted": True}}

    async def get_raw_document(self, payload):
        return {"request_id": "req", "ok": True, "result": {"found": False}}


class _FakeProjectDocumentClient:
    ingest_request: object | None = None
    search_request: object | None = None
    status_job_id: str | None = None
    delete_request: object | None = None
    started_task_request: object | None = None
    searched_documents_request: object | None = None
    task_status_job_id: str | None = None

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

    async def start_document_ingest_task(self, request: object) -> IngestResult:
        self.started_task_request = request
        return await self.ingest(request)

    async def search(self, request: object) -> str:
        self.search_request = request
        return "search-result"

    async def search_documents(self, request: object) -> str:
        self.searched_documents_request = request
        return await self.search(request)

    async def ingest_status(self, job_id: str) -> str:
        self.status_job_id = job_id
        return f"status:{job_id}"

    async def get_document_task_status(self, job_id: str) -> str:
        self.task_status_job_id = job_id
        return await self.ingest_status(job_id)

    async def delete_document(self, request: object) -> str:
        self.delete_request = request
        return "deleted"


class _ContextAwareProjectDocumentClient(_FakeProjectDocumentClient):
    def __init__(self) -> None:
        self.contexts: list[dict[str, object]] = []

    async def start_document_ingest_task(
        self,
        request: object,
        *,
        context: dict[str, object],
    ) -> IngestResult:
        self.contexts.append(context)
        return await super().start_document_ingest_task(request)

    async def search_documents(
        self,
        request: object,
        *,
        context: dict[str, object],
    ) -> str:
        self.contexts.append(context)
        return await super().search_documents(request)

    async def get_document_task_status(
        self,
        job_id: str,
        *,
        context: dict[str, object],
    ) -> str:
        self.contexts.append(context)
        return await super().get_document_task_status(job_id)

    async def delete_document(
        self,
        request: object,
        *,
        context: dict[str, object],
    ) -> str:
        self.contexts.append(context)
        return await super().delete_document(request)


class _FakeIngestionClient:
    ingest_request: object | None = None
    status_job_id: str | None = None

    async def ingest(self, request: object) -> IngestResult:
        self.ingest_request = request
        return IngestResult(
            job_id="job1",
            status=JobStatus.PENDING,
            doc_id="d1",
            project_id="p1",
            user_id="u1",
            kb_id="kb",
        )

    async def ingest_status(self, job_id: str) -> str:
        self.status_job_id = job_id
        return f"status:{job_id}"


class _FakeIngestionExecutor:
    ingest_request: object | None = None

    async def ingest(self, request: object) -> str:
        self.ingest_request = request
        return "accepted"


class _FakeIngestionApi:
    def __init__(
        self,
        *,
        ok: bool = True,
        code: str = "",
        message: str = "",
    ) -> None:
        self.ok = ok
        self.code = code
        self.message = message
        self.status_payload = None

    async def get_status(self, payload, *, fallback_request_id="ingestion-status"):
        self.status_payload = payload
        if self.ok:
            return {
                "request_id": payload.get("request_id", fallback_request_id),
                "ok": True,
                "result": {
                    "job": {
                        "job_id": "job1",
                        "status": JobStatus.COMPLETED.value,
                        "doc_id": "d1",
                        "metadata": {"project_id": "p1"},
                    }
                },
            }
        return {
            "request_id": payload.get("request_id", fallback_request_id),
            "ok": False,
            "error": {"code": self.code, "message": self.message},
        }


class _FakeIngestionJobs:
    record: IngestionJob | None = None

    async def get(self, job_id: str) -> IngestionJob | None:
        if self.record is not None and self.record.job_id == job_id:
            return self.record
        return None


class _FakeIngestionApp:
    def __init__(self) -> None:
        self.enabled = True
        self.topic = "custom.ingest"
        self.jobs = _FakeIngestionJobs()
        self.consumer = object()
        self.shutdown = AsyncMock()


class _FakeRetrievalClient:
    search_request: object | None = None
    delete_request: object | None = None

    async def search(self, request: object) -> str:
        self.search_request = request
        return "search-result"

    async def delete_document(self, request: object) -> str:
        self.delete_request = request
        return "deleted"


class _FakeRetrievalApp:
    search_request: object | None = None
    delete_request: object | None = None

    async def search(self, request: object) -> str:
        self.search_request = request
        return "retrieval-search"

    async def delete_document(self, request: object) -> str:
        self.delete_request = request
        return "retrieval-delete"


class _FakeProjectApp:
    def __init__(self) -> None:
        self.settings = _settings()
        self.gateway = _FakeGateway()
        self.engine = _FakeEngine()
        self.project_client: ProjectDocumentClient = _FakeProjectDocumentClient()
        self.server = object()
        self.health_checker = _FakeHealthChecker()
        self.jobs = _FakeIngestionJobs()

    async def shutdown(self) -> None:
        return None


class _FakeRemoteProjectClient:
    def __init__(self) -> None:
        self.shutdown = AsyncMock()


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
