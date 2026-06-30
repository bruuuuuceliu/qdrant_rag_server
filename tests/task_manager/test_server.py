"""Task manager server context tests."""

from __future__ import annotations

import asyncio

import pytest

from shared.contracts import MessageEnvelope, MessageType, TOPICS
from task_manager_service import TaskManagerDispatcher, TaskManagerServerContext


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


class QueueConsumer:
    def __init__(self, envelope: MessageEnvelope) -> None:
        self.envelope = envelope
        self.topics: list[str] = []
        self.consumed = False

    async def consume(self, topic: str) -> MessageEnvelope:
        self.topics.append(topic)
        if self.consumed:
            await asyncio.Event().wait()
        self.consumed = True
        return self.envelope


@pytest.mark.asyncio
async def test_task_manager_server_runs_each_loop_once() -> None:
    producer = FakeProducer()
    dispatcher = TaskManagerDispatcher(producer=producer)
    context = TaskManagerServerContext(
        dispatcher=dispatcher,
        intake_consumer=QueueConsumer(_intake()),
        task_event_consumer=QueueConsumer(_task_event()),
        task_result_consumer=QueueConsumer(_task_result()),
    )

    await context.run_intake_once()
    await context.run_task_event_once()
    await context.run_task_result_once()

    assert producer.published[0][0] == TOPICS.task_requests


@pytest.mark.asyncio
async def test_task_manager_server_start_stop_cancels_background_tasks() -> None:
    producer = FakeProducer()
    dispatcher = TaskManagerDispatcher(producer=producer)
    context = TaskManagerServerContext(
        dispatcher=dispatcher,
        intake_consumer=QueueConsumer(_intake()),
        task_event_consumer=QueueConsumer(_task_event()),
        task_result_consumer=QueueConsumer(_task_result()),
    )

    context.start()
    await asyncio.sleep(0)
    assert len(context._tasks) == 3
    await context.stop()

    assert context._tasks == []


def _intake() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "request": {"project_id": "p1"}},
    )


def _task_event() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.TASK_EVENT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "status": "running"},
    )


def _task_result() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.TASK_RESULT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "status": "completed", "result": {"ok": True}},
    )
