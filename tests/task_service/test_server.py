"""Task service server context tests."""

from __future__ import annotations

import asyncio

import pytest

from shared.contracts import MessageEnvelope, MessageType, TOPICS
from task_service import TaskServiceDispatcher, TaskServiceServerContext


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
async def test_task_service_server_runs_each_loop_once() -> None:
    producer = FakeProducer()
    dispatcher = TaskServiceDispatcher(producer=producer)
    context = TaskServiceServerContext(
        dispatcher=dispatcher,
        request_consumer=QueueConsumer(_task_request()),
        project_plan_result_consumers=(
            ("project.plan.results.a", QueueConsumer(_project_plan_result())),
            ("project.plan.results.b", QueueConsumer(_project_plan_result(operation="delete"))),
        ),
        helper_result_consumers=(
            (TOPICS.helper_retrieval_results, QueueConsumer(_helper_result())),
        ),
    )

    await context.run_request_once()
    await context.run_project_plan_result_once(topic="project.plan.results.b")
    await context.run_helper_result_once(topic=TOPICS.helper_retrieval_results)

    assert [published[0] for published in producer.published] == [
        TOPICS.task_events,
        TOPICS.project_plan_requests,
        TOPICS.helper_retrieval_commands,
        TOPICS.helper_storage_commands,
        TOPICS.task_events,
        TOPICS.task_events,
        TOPICS.task_results,
    ]
    assert context.project_plan_result_consumers[0][1].topics == []
    assert context.project_plan_result_consumers[1][1].topics == ["project.plan.results.b"]


@pytest.mark.asyncio
async def test_task_service_server_rejects_unknown_requested_consumer_topic() -> None:
    context = TaskServiceServerContext(
        dispatcher=TaskServiceDispatcher(producer=FakeProducer()),
        request_consumer=QueueConsumer(_task_request()),
        project_plan_result_consumers=(("project.plan.results", QueueConsumer(_project_plan_result())),),
        helper_result_consumers=(),
    )

    with pytest.raises(RuntimeError, match="project plan result consumer for topic missing"):
        await context.run_project_plan_result_once(topic="missing")

    with pytest.raises(RuntimeError, match="helper result consumers"):
        await context.run_helper_result_once()


@pytest.mark.asyncio
async def test_task_service_server_start_stop_cancels_background_tasks() -> None:
    context = TaskServiceServerContext(
        dispatcher=TaskServiceDispatcher(producer=FakeProducer()),
        request_consumer=QueueConsumer(_task_request()),
        project_plan_result_consumers=(("project.plan.results", QueueConsumer(_project_plan_result())),),
        helper_result_consumers=((TOPICS.helper_retrieval_results, QueueConsumer(_helper_result())),),
    )

    context.start()
    await asyncio.sleep(0)
    assert len(context._tasks) == 3
    await context.stop()

    assert context._tasks == []


def _task_request() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_manager_service",
        message_type=MessageType.TASK_REQUEST,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "request": {"project_id": "p1"}},
    )


def _project_plan_result(*, operation: str = "search") -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="project_service",
        message_type=MessageType.PROJECT_PLAN_RESULT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": operation, "plan": {"project_id": "p1"}},
    )


def _helper_result() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="retrieval_service",
        message_type=MessageType.HELPER_RESULT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "operation": "search",
            "helper": TOPICS.helper_retrieval_commands,
            "result": {"ok": True, "hits": []},
        },
    )
