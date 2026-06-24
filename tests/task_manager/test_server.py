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
        domain_result_consumers=((TOPICS.domain_project_results, QueueConsumer(_domain_result())),),
        helper_result_consumers=((TOPICS.helper_retrieval_results, QueueConsumer(_helper_result())),),
    )

    await context.run_intake_once()
    await context.run_domain_result_once()
    await context.run_helper_result_once()

    assert producer.published[0][0] == TOPICS.task_started
    assert producer.published[1][0] == TOPICS.domain_project_commands
    assert producer.published[2][0] == TOPICS.helper_retrieval_commands
    assert producer.published[3][0] == TOPICS.task_results


@pytest.mark.asyncio
async def test_task_manager_server_start_stop_cancels_background_tasks() -> None:
    producer = FakeProducer()
    dispatcher = TaskManagerDispatcher(producer=producer)
    context = TaskManagerServerContext(
        dispatcher=dispatcher,
        intake_consumer=QueueConsumer(_intake()),
        domain_result_consumers=(
            (TOPICS.domain_project_results, QueueConsumer(_domain_result())),
            (TOPICS.domain_workflow_log_results, QueueConsumer(_domain_result())),
        ),
        helper_result_consumers=(
            (TOPICS.helper_ingestion_results, QueueConsumer(_helper_result())),
            (TOPICS.helper_retrieval_results, QueueConsumer(_helper_result())),
            (TOPICS.helper_storage_results, QueueConsumer(_helper_result())),
        ),
    )

    context.start()
    await asyncio.sleep(0)
    assert len(context._tasks) == 6
    await context.stop()

    assert context._tasks == []


@pytest.mark.asyncio
async def test_task_manager_server_requires_configured_result_consumers() -> None:
    producer = FakeProducer()
    dispatcher = TaskManagerDispatcher(producer=producer)
    context = TaskManagerServerContext(
        dispatcher=dispatcher,
        intake_consumer=QueueConsumer(_intake()),
        domain_result_consumers=(),
        helper_result_consumers=(),
    )

    with pytest.raises(RuntimeError, match="domain result"):
        await context.run_domain_result_once()

    with pytest.raises(RuntimeError, match="helper result"):
        await context.run_helper_result_once()


def _intake() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "request": {"project_id": "p1"}},
    )


def _domain_result() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="project_service",
        message_type=MessageType.DOMAIN_RESULT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "plan": {"project_id": "p1"}},
    )


def _helper_result() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="retrieval_service",
        message_type=MessageType.HELPER_RESULT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "result": {"ok": True, "hits": []}},
    )
