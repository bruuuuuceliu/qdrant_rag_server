"""Task service orchestration dispatcher tests."""

from __future__ import annotations

import pytest

from shared.contracts import MessageEnvelope, MessageType, TOPICS
from task_service import InMemoryTaskStateRepository, TaskServiceDispatcher, TaskServiceSettings


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
async def test_dispatches_task_request_to_project_plan_request() -> None:
    producer = FakeMessageProducer()
    dispatcher = TaskServiceDispatcher(producer=producer)
    envelope = _task_request(operation="ingest")

    result = await dispatcher.dispatch_task_request(envelope)

    assert result.project_plan_topic == TOPICS.project_plan_requests
    assert [published[0] for published in producer.published] == [
        TOPICS.task_events,
        TOPICS.project_plan_requests,
    ]
    assert producer.published[0][1].message_type == MessageType.TASK_EVENT
    assert producer.published[0][1].payload["status"] == "running"
    request = producer.published[1][1]
    assert request.message_type == MessageType.PROJECT_PLAN_REQUEST
    assert request.payload["operation"] == "ingest"
    assert request.payload["request"]["project_id"] == "p1"


@pytest.mark.asyncio
async def test_run_once_consumes_task_request_topic() -> None:
    producer = FakeMessageProducer()
    settings = TaskServiceSettings(task_request_topic="custom.task.requests")
    dispatcher = TaskServiceDispatcher(producer=producer, settings=settings)
    consumer = FakeMessageConsumer(_task_request(operation="delete"))

    result = await dispatcher.run_once(consumer)

    assert consumer.topic == "custom.task.requests"
    assert result.operation == "delete"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "topics"),
    [
        ("ingest", (TOPICS.helper_ingestion_commands,)),
        ("search", (TOPICS.helper_retrieval_commands,)),
        ("delete", (TOPICS.helper_retrieval_commands, TOPICS.helper_storage_commands)),
    ],
)
async def test_dispatches_project_plan_result_to_helper_commands(
    operation: str,
    topics: tuple[str, ...],
) -> None:
    producer = FakeMessageProducer()
    state_repository = InMemoryTaskStateRepository()
    dispatcher = TaskServiceDispatcher(
        producer=producer,
        state_repository=state_repository,
    )

    result = await dispatcher.dispatch_project_plan_result(_project_plan_result(operation=operation))

    state = await state_repository.get("task-1")
    assert state is not None
    assert state.expected_helpers == set(topics)
    assert result.helper_topics == topics
    assert [published[0] for published in producer.published] == [*topics, TOPICS.task_events]
    assert producer.published[0][1].message_type == MessageType.HELPER_COMMAND
    assert producer.published[0][1].payload["plan"]["project_id"] == "p1"
    assert producer.published[-1][1].payload["status"] == "dispatched"


@pytest.mark.asyncio
async def test_rejects_unknown_project_plan_result_operation() -> None:
    dispatcher = TaskServiceDispatcher(producer=FakeMessageProducer())

    with pytest.raises(ValueError, match="unsupported helper"):
        await dispatcher.dispatch_project_plan_result(_project_plan_result(operation="export"))


@pytest.mark.asyncio
async def test_finalizes_successful_helper_result() -> None:
    producer = FakeMessageProducer()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_retrieval_commands,))
    dispatcher = TaskServiceDispatcher(
        producer=producer,
        state_repository=state_repository,
    )

    result = await dispatcher.finalize_helper_result(
        _helper_result(
            operation="search",
            helper=TOPICS.helper_retrieval_commands,
            result={"ok": True, "hits": []},
        )
    )

    assert result.status == "completed"
    assert [published[0] for published in producer.published] == [
        TOPICS.task_events,
        TOPICS.task_results,
    ]
    assert producer.published[0][1].payload["status"] == "completed"
    assert producer.published[1][1].payload["result"] == {"ok": True, "hits": []}


@pytest.mark.asyncio
async def test_helper_failure_metadata_is_preserved_in_task_result() -> None:
    producer = FakeMessageProducer()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_retrieval_commands,))
    dispatcher = TaskServiceDispatcher(
        producer=producer,
        state_repository=state_repository,
    )

    result = await dispatcher.finalize_helper_result(
        MessageEnvelope.create(
            producer="retrieval_service",
            message_type=MessageType.HELPER_RESULT,
            data_type="project_document",
            task_id="task-1",
            correlation_id="corr-1",
            payload={
                "operation": "search",
                "helper": TOPICS.helper_retrieval_commands,
                "result": {},
                "attempt": 2,
                "retryable": False,
                "error": "timeout",
            },
        )
    )

    assert result.status == "failed"
    assert producer.published[0][0] == TOPICS.task_dead_letters
    assert producer.published[2][1].payload["result"] == {
        "ok": False,
        "error": "timeout",
        "attempt": 2,
        "retryable": False,
    }


@pytest.mark.asyncio
async def test_retryable_helper_failure_republishes_helper_command_before_max_attempts() -> None:
    producer = FakeMessageProducer()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.record_helper_plan(
        "task-1",
        TOPICS.helper_retrieval_commands,
        operation="search",
        plan={"project_id": "p1"},
    )
    settings = TaskServiceSettings(max_attempts=3)
    dispatcher = TaskServiceDispatcher(
        producer=producer,
        state_repository=state_repository,
        settings=settings,
    )

    result = await dispatcher.finalize_helper_result(
        MessageEnvelope.create(
            producer="retrieval_service",
            message_type=MessageType.HELPER_RESULT,
            data_type="project_document",
            task_id="task-1",
            correlation_id="corr-1",
            payload={
                "operation": "search",
                "helper": TOPICS.helper_retrieval_commands,
                "result": {},
                "attempt": 1,
                "retryable": True,
                "error": "timeout",
                "source_message_id": "cmd-1",
            },
        )
    )

    assert result.status == "running"
    assert [published[0] for published in producer.published] == [
        TOPICS.helper_retrieval_commands,
        TOPICS.task_events,
    ]
    retry = producer.published[0][1]
    assert retry.payload["attempt"] == 2
    assert retry.payload["plan"] == {"project_id": "p1"}
    assert retry.payload["source_message_id"] == "cmd-1"


@pytest.mark.asyncio
async def test_terminal_helper_failure_publishes_dead_letter_and_final_result() -> None:
    producer = FakeMessageProducer()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_retrieval_commands,))
    settings = TaskServiceSettings(max_attempts=2, dead_letter_topic="task.dead")
    dispatcher = TaskServiceDispatcher(
        producer=producer,
        state_repository=state_repository,
        settings=settings,
    )

    result = await dispatcher.finalize_helper_result(
        MessageEnvelope.create(
            producer="retrieval_service",
            message_type=MessageType.HELPER_RESULT,
            data_type="project_document",
            task_id="task-1",
            correlation_id="corr-1",
            payload={
                "operation": "search",
                "helper": TOPICS.helper_retrieval_commands,
                "result": {},
                "attempt": 2,
                "retryable": True,
                "error": "timeout",
                "source_message_id": "cmd-1",
            },
        )
    )

    assert result.status == "failed"
    assert [published[0] for published in producer.published] == [
        "task.dead",
        TOPICS.task_events,
        TOPICS.task_results,
    ]
    dead_letter = producer.published[0][1]
    assert dead_letter.message_type == MessageType.TASK_STEP
    assert dead_letter.payload["attempt"] == 2
    assert dead_letter.payload["retryable"] is True
    assert dead_letter.payload["error"] == "timeout"
    assert dead_letter.payload["source_topic"] == TOPICS.helper_retrieval_commands


@pytest.mark.asyncio
async def test_waits_for_all_expected_helpers_before_final_result() -> None:
    producer = FakeMessageProducer()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers(
        "task-1",
        (TOPICS.helper_ingestion_commands, TOPICS.helper_retrieval_index_commands),
    )
    dispatcher = TaskServiceDispatcher(
        producer=producer,
        state_repository=state_repository,
    )

    first = await dispatcher.finalize_helper_result(
        _helper_result(
            operation="ingest",
            helper=TOPICS.helper_ingestion_commands,
            result={"ok": True, "job_id": "job-1"},
        )
    )

    assert first.status == "running"
    assert [published[0] for published in producer.published] == [TOPICS.task_events]

    final = await dispatcher.finalize_helper_result(
        _helper_result(
            operation="ingest",
            helper=TOPICS.helper_retrieval_index_commands,
            result={"ok": True, "indexed": 3},
        )
    )

    assert final.status == "completed"
    assert producer.published[-1][0] == TOPICS.task_results
    assert producer.published[-1][1].payload["result"] == {
        "helpers": {
            TOPICS.helper_ingestion_commands: {"ok": True, "job_id": "job-1"},
            TOPICS.helper_retrieval_index_commands: {"ok": True, "indexed": 3},
        }
    }


@pytest.mark.asyncio
async def test_duplicate_helper_result_does_not_publish_second_final_result() -> None:
    producer = FakeMessageProducer()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_retrieval_commands,))
    dispatcher = TaskServiceDispatcher(
        producer=producer,
        state_repository=state_repository,
    )
    envelope = _helper_result(
        operation="search",
        helper=TOPICS.helper_retrieval_commands,
        result={"ok": True, "hits": []},
    )

    first = await dispatcher.finalize_helper_result(envelope)
    second = await dispatcher.finalize_helper_result(envelope)

    assert first.status == "completed"
    assert second.status == "completed"
    assert [published[0] for published in producer.published].count(TOPICS.task_results) == 1


@pytest.mark.asyncio
async def test_ingest_helper_result_dispatches_storage_and_retrieval_index() -> None:
    producer = FakeMessageProducer()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_ingestion_commands,))
    dispatcher = TaskServiceDispatcher(
        producer=producer,
        state_repository=state_repository,
    )

    result = await dispatcher.finalize_helper_result(
        _helper_result(
            operation="ingest",
            helper=TOPICS.helper_ingestion_commands,
            result={
                "ok": True,
                "job_id": "job-1",
                "storage_request": {
                    "operation": "put",
                    "key": "raw/p1/u1/d1",
                    "value": "raw text",
                },
                "index_request": {"collection_name": "docs", "chunks": []},
            },
        )
    )

    assert result.status == "running"
    assert [published[0] for published in producer.published] == [
        TOPICS.helper_storage_commands,
        TOPICS.helper_retrieval_index_commands,
        TOPICS.task_events,
    ]
    assert producer.published[0][1].payload["operation"] == "put"
    assert producer.published[0][1].payload["plan"]["key"] == "raw/p1/u1/d1"
    state = await state_repository.get("task-1")
    assert state is not None
    assert state.expected_helpers == {
        TOPICS.helper_ingestion_commands,
        TOPICS.helper_storage_commands,
        TOPICS.helper_retrieval_index_commands,
    }


def _task_request(*, operation: str) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_manager_service",
        message_type=MessageType.TASK_REQUEST,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "operation": operation,
            "request": {"project_id": "p1"},
            "context": {"auth_context": {"subject_id": "u1"}},
        },
    )


def _project_plan_result(*, operation: str) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="project_service",
        message_type=MessageType.PROJECT_PLAN_RESULT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": operation, "plan": {"project_id": "p1"}},
    )


def _helper_result(*, operation: str, helper: str, result: dict[str, object]) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="retrieval_service",
        message_type=MessageType.HELPER_RESULT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": operation, "helper": helper, "result": result},
    )
