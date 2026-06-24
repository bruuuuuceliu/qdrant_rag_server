"""Task manager dispatcher tests."""

from __future__ import annotations

import pytest

from shared.contracts import MessageEnvelope, MessageType, TOPICS
from redis_status_node import InMemoryTaskStatusStore
from task_manager_service import InMemoryTaskStateRepository, TaskManagerDispatcher, TaskManagerSettings


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
async def test_dispatches_project_intake_to_project_domain_command() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    dispatcher = TaskManagerDispatcher(producer=producer, status_store=status_store)
    envelope = _intake(data_type="project_document", operation="ingest")

    result = await dispatcher.dispatch_intake(envelope)

    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.status == "running"
    assert status.operation == "ingest"
    assert result.domain_topic == TOPICS.domain_project_commands
    assert producer.published[0][0] == TOPICS.task_started
    assert producer.published[0][1].message_type == MessageType.TASK_STARTED
    assert producer.published[1][0] == TOPICS.domain_project_commands
    assert producer.published[1][1].message_type == MessageType.DOMAIN_COMMAND
    assert producer.published[1][1].payload["operation"] == "ingest"
    assert producer.published[1][1].payload["request"]["project_id"] == "p1"


@pytest.mark.asyncio
async def test_dispatches_workflow_intake_to_workflow_domain_command() -> None:
    producer = FakeMessageProducer()
    dispatcher = TaskManagerDispatcher(producer=producer)

    result = await dispatcher.dispatch_intake(_intake(data_type="workflow_log", operation="search"))

    assert result.domain_topic == TOPICS.domain_workflow_log_commands
    assert producer.published[1][0] == TOPICS.domain_workflow_log_commands


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
@pytest.mark.parametrize(
    ("operation", "topics"),
    [
        ("ingest", (TOPICS.helper_ingestion_commands,)),
        ("search", (TOPICS.helper_retrieval_commands,)),
        ("delete", (TOPICS.helper_retrieval_commands, TOPICS.helper_storage_commands)),
    ],
)
async def test_dispatches_domain_result_to_helper_command(operation: str, topics: tuple[str, ...]) -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
        state_repository=state_repository,
    )

    result = await dispatcher.dispatch_domain_result(_domain_result(operation=operation))

    state = await state_repository.get("task-1")
    assert state is not None
    assert state.expected_helpers == set(topics)
    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.status == "dispatched"
    assert result.helper_topics == topics
    assert [published[0] for published in producer.published] == list(topics)
    assert producer.published[0][1].message_type == MessageType.HELPER_COMMAND
    assert producer.published[0][1].payload["plan"]["project_id"] == "p1"


@pytest.mark.asyncio
async def test_rejects_unknown_domain_result_operation() -> None:
    dispatcher = TaskManagerDispatcher(producer=FakeMessageProducer())

    with pytest.raises(ValueError, match="unsupported helper"):
        await dispatcher.dispatch_domain_result(_domain_result(operation="export"))


@pytest.mark.asyncio
async def test_finalizes_workflow_domain_result_without_helper_dispatch() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    settings = TaskManagerSettings(completed_ttl_seconds=99)
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
        settings=settings,
    )

    result = await dispatcher.dispatch_domain_result(
        MessageEnvelope.create(
            producer="workflow_log_service",
            message_type=MessageType.DOMAIN_RESULT,
            data_type="workflow_log",
            task_id="task-1",
            correlation_id="corr-1",
            payload={"operation": "list", "result": {"ok": True, "entries": []}},
        )
    )

    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.status == "completed"
    assert status.result == {"ok": True, "entries": []}
    assert status_store.ttls["task-1"] == 99
    assert result.helper_topics == ()
    assert producer.published[0][0] == TOPICS.task_results
    assert producer.published[0][1].payload["status"] == "completed"


@pytest.mark.asyncio
async def test_finalizes_successful_helper_result_with_completed_ttl() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_retrieval_commands,))
    settings = TaskManagerSettings(completed_ttl_seconds=99)
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
        state_repository=state_repository,
        settings=settings,
    )

    result = await dispatcher.finalize_helper_result(
        _helper_result(
            operation="search",
            helper=TOPICS.helper_retrieval_commands,
            result={"ok": True, "hits": []},
        )
    )

    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.status == "completed"
    assert status.result == {"ok": True, "hits": []}
    assert status_store.ttls["task-1"] == 99
    assert result.status == "completed"
    assert producer.published[0][0] == TOPICS.task_results
    assert producer.published[0][1].payload["status"] == "completed"


@pytest.mark.asyncio
async def test_finalizes_failed_helper_result() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_ingestion_commands,))
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
        state_repository=state_repository,
    )

    result = await dispatcher.finalize_helper_result(
        _helper_result(
            operation="ingest",
            helper=TOPICS.helper_ingestion_commands,
            result={"ok": False, "error": "bad"},
        )
    )

    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.status == "failed"
    assert result.status == "failed"
    assert producer.published[0][1].payload["status"] == "failed"


@pytest.mark.asyncio
async def test_helper_failure_metadata_is_preserved_in_status_and_result() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_retrieval_commands,))
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
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

    status = await status_store.get_status("task-1")
    assert result.status == "failed"
    assert status is not None
    assert status.result == {
        "ok": False,
        "error": "timeout",
        "attempt": 2,
        "retryable": False,
    }
    assert producer.published[1][1].payload["result"] == status.result


@pytest.mark.asyncio
async def test_retryable_helper_failure_republishes_helper_command_before_max_attempts() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.record_helper_plan(
        "task-1",
        TOPICS.helper_retrieval_commands,
        operation="search",
        plan={"project_id": "p1"},
    )
    settings = TaskManagerSettings(max_attempts=3)
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
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

    status = await status_store.get_status("task-1")
    assert result.status == "running"
    assert status is not None
    assert status.status == "running"
    assert [published[0] for published in producer.published] == [TOPICS.helper_retrieval_commands]
    retry = producer.published[0][1]
    assert retry.payload["attempt"] == 2
    assert retry.payload["plan"] == {"project_id": "p1"}
    assert retry.payload["source_message_id"] == "cmd-1"


@pytest.mark.asyncio
async def test_terminal_helper_failure_publishes_dead_letter_and_final_result() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_retrieval_commands,))
    settings = TaskManagerSettings(max_attempts=2, dead_letter_topic="task.dead")
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
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

    status = await status_store.get_status("task-1")
    assert result.status == "failed"
    assert status is not None
    assert status.status == "failed"
    assert [published[0] for published in producer.published] == ["task.dead", TOPICS.task_results]
    dead_letter = producer.published[0][1]
    assert dead_letter.message_type == MessageType.TASK_STEP
    assert dead_letter.payload["attempt"] == 2
    assert dead_letter.payload["retryable"] is True
    assert dead_letter.payload["error"] == "timeout"
    assert dead_letter.payload["source_topic"] == TOPICS.helper_retrieval_commands


@pytest.mark.asyncio
async def test_waits_for_all_expected_helpers_before_final_result() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers(
        "task-1",
        (TOPICS.helper_ingestion_commands, TOPICS.helper_retrieval_index_commands),
    )
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
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
    assert producer.published == []
    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.status == "running"

    final = await dispatcher.finalize_helper_result(
        _helper_result(
            operation="ingest",
            helper=TOPICS.helper_retrieval_index_commands,
            result={"ok": True, "indexed": 3},
        )
    )

    assert final.status == "completed"
    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.result == {
        "helpers": {
            TOPICS.helper_ingestion_commands: {"ok": True, "job_id": "job-1"},
            TOPICS.helper_retrieval_index_commands: {"ok": True, "indexed": 3},
        }
    }
    assert producer.published[0][0] == TOPICS.task_results
    assert producer.published[0][1].payload["result"] == status.result


@pytest.mark.asyncio
async def test_duplicate_helper_result_does_not_publish_second_final_result() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_retrieval_commands,))
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
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
    assert len(producer.published) == 1
    assert producer.published[0][0] == TOPICS.task_results


@pytest.mark.asyncio
async def test_ingest_helper_result_dispatches_retrieval_index_before_final_result() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_ingestion_commands,))
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
        state_repository=state_repository,
    )

    first = await dispatcher.finalize_helper_result(
        _helper_result(
            operation="ingest",
            helper=TOPICS.helper_ingestion_commands,
            result={
                "ok": True,
                "job_id": "job-1",
                "index_request": {"collection_name": "docs", "chunks": []},
            },
        )
    )

    assert first.status == "running"
    assert producer.published[0][0] == TOPICS.helper_retrieval_index_commands
    assert producer.published[0][1].payload["plan"] == {"collection_name": "docs", "chunks": []}
    status = await status_store.get_status("task-1")
    assert status is not None
    assert status.status == "running"


@pytest.mark.asyncio
async def test_ingest_helper_result_dispatches_storage_and_retrieval_index() -> None:
    producer = FakeMessageProducer()
    status_store = InMemoryTaskStatusStore()
    state_repository = InMemoryTaskStateRepository()
    await state_repository.set_expected_helpers("task-1", (TOPICS.helper_ingestion_commands,))
    dispatcher = TaskManagerDispatcher(
        producer=producer,
        status_store=status_store,
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


def _domain_result(*, operation: str) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="project_service",
        message_type=MessageType.DOMAIN_RESULT,
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
