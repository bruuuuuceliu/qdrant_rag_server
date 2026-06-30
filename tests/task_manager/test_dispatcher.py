"""Task manager intake/status dispatcher tests."""

from __future__ import annotations

import pytest

from redis_status_node import InMemoryTaskStatusStore
from shared.contracts import MessageEnvelope, MessageType, TOPICS
from task_manager_service import TaskManagerDispatcher, TaskManagerSettings


class FakeMessageProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


class FakeMessageConsumer:
    def __init__(self, envelope: MessageEnvelope) -> None:
        self.envelope = envelope
        self.topic = ""

    async def consume(self, topic: str) -> MessageEnvelope:
        self.topic = topic
        return self.envelope


@pytest.mark.asyncio
async def test_dispatches_intake_to_task_request_only() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    dispatcher = TaskManagerDispatcher(producer=producer, status_store=status_store)
    envelope = _intake(data_type="project_document", operation="ingest")

    result = await dispatcher.dispatch_intake(envelope)

    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.status == "queued"
    assert status.operation == "ingest"
    assert result.task_request_topic == TOPICS.task_requests
    assert [published[0] for published in producer.published] == [TOPICS.task_requests]
    request = producer.published[0][1]
    assert request.message_type == MessageType.TASK_REQUEST
    assert request.payload["operation"] == "ingest"
    assert request.payload["request"]["project_id"] == "p1"
    assert TOPICS.project_plan_requests not in [published[0] for published in producer.published]
    assert TOPICS.helper_ingestion_commands not in [published[0] for published in producer.published]


@pytest.mark.asyncio
async def test_run_once_consumes_task_intake_topic() -> None:
    producer = FakeMessageProducer()
    settings = TaskManagerSettings(task_intake_topic="custom.task.intake")
    dispatcher = TaskManagerDispatcher(producer=producer, settings=settings)
    consumer = FakeMessageConsumer(_intake(data_type="project_document", operation="delete"))

    result = await dispatcher.run_once(consumer)

    assert consumer.topic == "custom.task.intake"
    assert result.operation == "delete"


@pytest.mark.asyncio
async def test_rejects_intake_without_operation() -> None:
    dispatcher = TaskManagerDispatcher(producer=FakeMessageProducer())
    envelope = _intake(data_type="project_document", operation="")

    with pytest.raises(ValueError, match="operation"):
        await dispatcher.dispatch_intake(envelope)


@pytest.mark.asyncio
async def test_task_event_updates_redis_status() -> None:
    status_store = InMemoryTaskStatusStore()
    dispatcher = TaskManagerDispatcher(
        producer=FakeMessageProducer(),
        status_store=status_store,
    )

    result = await dispatcher.update_from_task_event(
        MessageEnvelope.create(
            producer="task_service",
            message_type=MessageType.TASK_EVENT,
            data_type="project_document",
            task_id="task-1",
            correlation_id="corr-1",
            payload={
                "operation": "search",
                "status": "running",
                "event": "task.waiting_helpers",
                "result": {"ok": True},
            },
        )
    )

    status = await status_store.get_status("task-1")
    assert result.status == "running"
    assert status is not None
    assert status.status == "running"
    assert status.result == {"ok": True}


@pytest.mark.asyncio
async def test_task_result_updates_redis_status_with_completed_ttl() -> None:
    status_store = InMemoryTaskStatusStore()
    settings = TaskManagerSettings(completed_ttl_seconds=99)
    dispatcher = TaskManagerDispatcher(
        producer=FakeMessageProducer(),
        status_store=status_store,
        settings=settings,
    )

    result = await dispatcher.update_from_task_result(
        MessageEnvelope.create(
            producer="task_service",
            message_type=MessageType.TASK_RESULT,
            data_type="project_document",
            task_id="task-1",
            correlation_id="corr-1",
            payload={
                "operation": "search",
                "status": "completed",
                "result": {"ok": True, "hits": []},
            },
        )
    )

    status = await status_store.get_status("task-1")
    assert result.status == "completed"
    assert status is not None
    assert status.status == "completed"
    assert status.result == {"ok": True, "hits": []}
    assert status_store.ttls["task-1"] == 99


def _intake(*, data_type: str, operation: str) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type=data_type,
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "operation": operation,
            "request": {"project_id": "p1"},
            "context": {"auth_context": {"subject_id": "u1"}},
        },
    )
