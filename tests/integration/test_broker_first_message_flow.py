"""Broker-first message flow smoke tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ingestion_service.jobs import MemoryIngestionJobRepository
from ingestion_service.server import BrokerIngestionApp, IngestionHelperHandler
from ingestion_service.service import IngestionService
from manager_service.service import ManagerService
from project_service import ProjectDomainHandler
from redis_status_node import InMemoryTaskStatusStore
from retrieval_service.indexing import RetrievalIndexHelperHandler
from retrieval_service.server import RetrievalHelperHandler
from shared.contracts import MessageEnvelope, TOPICS
from storage_node import FilesystemStorageService, StorageHelperHandler
from task_manager_service import TaskManagerDispatcher
from task_service import InMemoryTaskStateRepository, TaskServiceDispatcher


class EnvelopeBus:
    def __init__(self) -> None:
        self.messages: dict[str, list[MessageEnvelope]] = {}

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.messages.setdefault(topic, []).append(envelope)

    def pop(self, topic: str) -> MessageEnvelope:
        return self.messages[topic].pop(0)


class Planning:
    async def plan_ingest(self, request: object) -> object:
        return Plan(
            project_id=str(request.get("project_id", "")),
            operation="ingest",
            collection_name="rag_p1_v1",
            user_id=str(request.get("user_id", "")),
            kb_id=str(request.get("kb_id", "")),
            doc_id=str(request.get("doc_id", "")),
            source_uri=str(request.get("source_uri", "")),
            content_type=str(request.get("content_type", "")),
            raw_text=str(request.get("raw_text", "")),
        )

    async def plan_search(self, request: object) -> object:
        return Plan(project_id=str(request.get("project_id", "")), operation="search")

    async def plan_delete(self, request: object) -> object:
        return Plan(
            project_id=str(request.get("project_id", "")),
            operation="delete",
            storage_key="raw/doc.txt",
        )


@dataclass(frozen=True, slots=True)
class Plan:
    project_id: str
    operation: str
    storage_key: str = ""
    collection_name: str = ""
    user_id: str = ""
    kb_id: str = ""
    doc_id: str = ""
    source_uri: str = ""
    content_type: str = ""
    raw_text: str = ""


class RetrievalApi:
    async def search(self, payload: dict[str, object], *, fallback_request_id: str) -> dict[str, object]:
        return {"ok": True, "hits": [{"project_id": payload["project_id"], "score": 1.0}]}

    async def delete_document(
        self,
        payload: dict[str, object],
        *,
        fallback_request_id: str,
    ) -> dict[str, object]:
        return {"ok": True, "deleted": True, "project_id": payload["project_id"]}


class IndexingService:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def index_chunks(self, request: object) -> dict[str, object]:
        self.requests.append(request)
        return {
            "chunk_count": len(request.chunks),
            "dense_enabled": True,
            "sparse_enabled": False,
        }


@pytest.mark.asyncio
async def test_ingest_flow_stores_raw_indexes_chunks_and_publishes_final_result(tmp_path) -> None:
    bus = EnvelopeBus()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    manager = ManagerService(task_producer=bus)
    task_manager = TaskManagerDispatcher(producer=bus, status_store=status_store)
    task_service = TaskServiceDispatcher(producer=bus, state_repository=state_repository)
    project = ProjectDomainHandler(planning=Planning(), producer=bus)
    ingestion = BrokerIngestionApp(
        jobs=MemoryIngestionJobRepository(),
        ingestion_service=IngestionService(),
    )
    ingestion_handler = IngestionHelperHandler(app=ingestion, producer=bus)
    storage = StorageHelperHandler(
        storage=FilesystemStorageService(root=tmp_path),
        producer=bus,
    )
    indexing = IndexingService()
    retrieval_index = RetrievalIndexHelperHandler(indexing_service=indexing, producer=bus)

    accepted = await manager.ingest(
        {
            "project_id": "p1",
            "user_id": "u1",
            "kb_id": "kb",
            "doc_id": "d1",
            "source_uri": "memory://d1",
            "content_type": "text/plain",
            "raw_text": "broker ingest text",
            "metadata": {"data_type": "project_document"},
        }
    )

    await task_manager.dispatch_intake(bus.pop(TOPICS.task_intake))
    await task_service.dispatch_task_request(bus.pop(TOPICS.task_requests))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await project.handle(bus.pop(TOPICS.project_plan_requests))
    await task_service.dispatch_project_plan_result(bus.pop(TOPICS.project_plan_results))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await ingestion_handler.handle(bus.pop(TOPICS.helper_ingestion_commands))
    first = await task_service.finalize_helper_result(bus.pop(TOPICS.helper_ingestion_results))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await storage.handle(bus.pop(TOPICS.helper_storage_commands))
    second = await task_service.finalize_helper_result(bus.pop(TOPICS.helper_storage_results))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await retrieval_index.handle(bus.pop(TOPICS.helper_retrieval_index_commands))
    final_result = await task_service.finalize_helper_result(
        bus.pop(TOPICS.helper_retrieval_index_results)
    )
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await task_manager.update_from_task_result(bus.pop(TOPICS.task_results))

    status = await status_store.get_status(accepted.task_id)

    assert first.status == "running"
    assert second.status == "running"
    assert final_result.status == "completed"
    assert status is not None
    assert status.status == "completed"
    assert (tmp_path / "p1" / "u1" / "d1").read_text(encoding="utf-8") == "broker ingest text"
    assert indexing.requests[0].collection_name == "rag_p1_v1"
    assert status.result["helpers"][TOPICS.helper_storage_commands]["ok"] is True
    assert status.result["helpers"][TOPICS.helper_retrieval_index_commands]["chunk_count"] == 1


@pytest.mark.asyncio
async def test_manager_to_task_manager_to_task_service_to_project_to_retrieval_to_status_flow() -> None:
    bus = EnvelopeBus()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    manager = ManagerService(task_producer=bus)
    task_manager = TaskManagerDispatcher(producer=bus, status_store=status_store)
    task_service = TaskServiceDispatcher(producer=bus, state_repository=state_repository)
    project = ProjectDomainHandler(planning=Planning(), producer=bus)
    retrieval = RetrievalHelperHandler(api=RetrievalApi(), producer=bus)

    accepted = await manager.search(
        {"project_id": "p1", "user_id": "u1", "metadata": {"data_type": "project_document"}}
    )
    await task_manager.dispatch_intake(bus.pop(TOPICS.task_intake))
    await task_service.dispatch_task_request(bus.pop(TOPICS.task_requests))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await project.handle(bus.pop(TOPICS.project_plan_requests))
    await task_service.dispatch_project_plan_result(bus.pop(TOPICS.project_plan_results))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await retrieval.handle(bus.pop(TOPICS.helper_retrieval_commands))
    await task_service.finalize_helper_result(bus.pop(TOPICS.helper_retrieval_results))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await task_manager.update_from_task_result(bus.pop(TOPICS.task_results))

    status = await status_store.get_status(accepted.task_id)

    assert status is not None
    assert status.status == "completed"
    assert status.result["hits"][0]["project_id"] == "p1"


@pytest.mark.asyncio
async def test_task_service_waits_for_retrieval_and_storage_results(tmp_path) -> None:
    bus = EnvelopeBus()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    manager = ManagerService(task_producer=bus)
    task_manager = TaskManagerDispatcher(producer=bus, status_store=status_store)
    task_service = TaskServiceDispatcher(producer=bus, state_repository=state_repository)
    project = ProjectDomainHandler(planning=Planning(), producer=bus)
    retrieval = RetrievalHelperHandler(api=RetrievalApi(), producer=bus)
    storage = StorageHelperHandler(
        storage=FilesystemStorageService(root=tmp_path),
        producer=bus,
    )

    accepted = await manager.delete(
        {"project_id": "p1", "user_id": "u1", "metadata": {"data_type": "project_document"}}
    )
    await task_manager.dispatch_intake(bus.pop(TOPICS.task_intake))
    await task_service.dispatch_task_request(bus.pop(TOPICS.task_requests))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await project.handle(bus.pop(TOPICS.project_plan_requests))
    await task_service.dispatch_project_plan_result(bus.pop(TOPICS.project_plan_results))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))

    await retrieval.handle(bus.pop(TOPICS.helper_retrieval_commands))
    first = await task_service.finalize_helper_result(bus.pop(TOPICS.helper_retrieval_results))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await storage.handle(bus.pop(TOPICS.helper_storage_commands))
    final_result = await task_service.finalize_helper_result(bus.pop(TOPICS.helper_storage_results))
    await task_manager.update_from_task_event(bus.pop(TOPICS.task_events))
    await task_manager.update_from_task_result(bus.pop(TOPICS.task_results))

    status = await status_store.get_status(accepted.task_id)

    assert first.status == "running"
    assert final_result.status == "completed"
    assert status is not None
    assert status.status == "completed"
    assert status.result["helpers"][TOPICS.helper_retrieval_commands]["deleted"] is True
    assert status.result["helpers"][TOPICS.helper_storage_commands]["ok"] is True
