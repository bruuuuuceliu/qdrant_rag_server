"""Broker consumer commit-boundary tests for service loops."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from ingestion_service.server import IngestionHelperServerContext
from project_service import ProjectDomainServerContext
from retrieval_service.indexing import RetrievalIndexHelperServerContext
from retrieval_service.server import RetrievalHelperServerContext
from shared.contracts import MessageEnvelope, MessageType, TOPICS
from storage_node import StorageHelperServerContext
from task_manager_service import TaskManagerDispatcher, TaskManagerServerContext
from task_service import TaskServiceDispatcher, TaskServiceServerContext
from workflow_log_service import WorkflowLogDomainServerContext


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


class CommittableConsumer:
    def __init__(self, envelope: MessageEnvelope) -> None:
        self.envelope = envelope
        self.topics: list[str] = []
        self.commit_count = 0

    async def consume(self, topic: str) -> MessageEnvelope:
        self.topics.append(topic)
        return self.envelope

    async def commit(self) -> None:
        self.commit_count += 1


class Handler:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.handled: list[MessageEnvelope] = []

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        self.handled.append(envelope)
        if self.fail:
            raise RuntimeError("handler failed")
        return envelope


ContextFactory = Callable[[Handler, CommittableConsumer], object]
EnvelopeFactory = Callable[[], MessageEnvelope]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context_factory", "envelope", "topic"),
    [
        pytest.param(
            lambda handler, consumer: ProjectDomainServerContext(handler=handler, consumer=consumer),
            lambda: _project_plan_request(),
            TOPICS.project_plan_requests,
            id="project-plan",
        ),
        pytest.param(
            lambda handler, consumer: IngestionHelperServerContext(
                handler=handler,
                consumer=consumer,
            ),
            lambda: _helper_command(operation="ingest", helper=TOPICS.helper_ingestion_commands),
            TOPICS.helper_ingestion_commands,
            id="ingestion-helper",
        ),
        pytest.param(
            lambda handler, consumer: RetrievalHelperServerContext(
                handler=handler,
                consumer=consumer,
            ),
            lambda: _helper_command(operation="search", helper=TOPICS.helper_retrieval_commands),
            TOPICS.helper_retrieval_commands,
            id="retrieval-helper",
        ),
        pytest.param(
            lambda handler, consumer: RetrievalIndexHelperServerContext(
                handler=handler,
                consumer=consumer,
            ),
            lambda: _helper_command(
                operation="ingest",
                helper=TOPICS.helper_retrieval_index_commands,
            ),
            TOPICS.helper_retrieval_index_commands,
            id="retrieval-index-helper",
        ),
        pytest.param(
            lambda handler, consumer: StorageHelperServerContext(handler=handler, consumer=consumer),
            lambda: _helper_command(operation="put", helper=TOPICS.helper_storage_commands),
            TOPICS.helper_storage_commands,
            id="storage-helper",
        ),
        pytest.param(
            lambda handler, consumer: WorkflowLogDomainServerContext(
                handler=handler,
                consumer=consumer,
            ),
            lambda: _workflow_command(),
            TOPICS.domain_workflow_log_commands,
            id="workflow-command",
        ),
    ],
)
async def test_domain_and_helper_contexts_commit_after_successful_handler(
    context_factory: ContextFactory,
    envelope: EnvelopeFactory,
    topic: str,
) -> None:
    handler = Handler()
    message = envelope()
    consumer = CommittableConsumer(message)
    context = context_factory(handler, consumer)

    await context.run_once()

    assert consumer.topics == [topic]
    assert handler.handled == [message]
    assert consumer.commit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context_factory", "envelope"),
    [
        pytest.param(
            lambda handler, consumer: ProjectDomainServerContext(handler=handler, consumer=consumer),
            lambda: _project_plan_request(),
            id="project-plan",
        ),
        pytest.param(
            lambda handler, consumer: IngestionHelperServerContext(
                handler=handler,
                consumer=consumer,
            ),
            lambda: _helper_command(operation="ingest", helper=TOPICS.helper_ingestion_commands),
            id="ingestion-helper",
        ),
        pytest.param(
            lambda handler, consumer: RetrievalHelperServerContext(
                handler=handler,
                consumer=consumer,
            ),
            lambda: _helper_command(operation="search", helper=TOPICS.helper_retrieval_commands),
            id="retrieval-helper",
        ),
        pytest.param(
            lambda handler, consumer: RetrievalIndexHelperServerContext(
                handler=handler,
                consumer=consumer,
            ),
            lambda: _helper_command(
                operation="ingest",
                helper=TOPICS.helper_retrieval_index_commands,
            ),
            id="retrieval-index-helper",
        ),
        pytest.param(
            lambda handler, consumer: StorageHelperServerContext(handler=handler, consumer=consumer),
            lambda: _helper_command(operation="put", helper=TOPICS.helper_storage_commands),
            id="storage-helper",
        ),
        pytest.param(
            lambda handler, consumer: WorkflowLogDomainServerContext(
                handler=handler,
                consumer=consumer,
            ),
            lambda: _workflow_command(),
            id="workflow-command",
        ),
    ],
)
async def test_domain_and_helper_contexts_do_not_commit_after_handler_failure(
    context_factory: ContextFactory,
    envelope: EnvelopeFactory,
) -> None:
    handler = Handler(fail=True)
    message = envelope()
    consumer = CommittableConsumer(message)
    context = context_factory(handler, consumer)

    with pytest.raises(RuntimeError, match="handler failed"):
        await context.run_once()

    assert handler.handled == [message]
    assert consumer.commit_count == 0


@pytest.mark.asyncio
async def test_workflow_log_audit_consumer_commits_only_after_successful_handler() -> None:
    handler = Handler()
    audit_consumer = CommittableConsumer(_audit_event())
    context = WorkflowLogDomainServerContext(
        handler=handler,
        consumer=CommittableConsumer(_workflow_command()),
        audit_consumer=audit_consumer,
    )

    await context.run_audit_once()

    assert audit_consumer.topics == [TOPICS.audit_events]
    assert audit_consumer.commit_count == 1

    failing_handler = Handler(fail=True)
    failing_audit_consumer = CommittableConsumer(_audit_event())
    failing_context = WorkflowLogDomainServerContext(
        handler=failing_handler,
        consumer=CommittableConsumer(_workflow_command()),
        audit_consumer=failing_audit_consumer,
    )

    with pytest.raises(RuntimeError, match="handler failed"):
        await failing_context.run_audit_once()

    assert failing_audit_consumer.commit_count == 0


@pytest.mark.asyncio
async def test_task_manager_context_commits_only_after_successful_dispatch() -> None:
    producer = FakeProducer()
    intake_consumer = CommittableConsumer(_task_intake())
    event_consumer = CommittableConsumer(_task_event())
    result_consumer = CommittableConsumer(_task_result())
    context = TaskManagerServerContext(
        dispatcher=TaskManagerDispatcher(producer=producer),
        intake_consumer=intake_consumer,
        task_event_consumer=event_consumer,
        task_result_consumer=result_consumer,
    )

    await context.run_intake_once()
    await context.run_task_event_once()
    await context.run_task_result_once()

    assert intake_consumer.commit_count == 1
    assert event_consumer.commit_count == 1
    assert result_consumer.commit_count == 1
    assert [published[0] for published in producer.published] == [TOPICS.task_requests]

    failing_consumer = CommittableConsumer(_task_intake(payload={}))
    failing_context = TaskManagerServerContext(
        dispatcher=TaskManagerDispatcher(producer=FakeProducer()),
        intake_consumer=failing_consumer,
        task_event_consumer=CommittableConsumer(_task_event()),
        task_result_consumer=CommittableConsumer(_task_result()),
    )

    with pytest.raises(Exception):
        await failing_context.run_intake_once()

    assert failing_consumer.commit_count == 0


@pytest.mark.asyncio
async def test_task_service_context_commits_only_after_successful_dispatch() -> None:
    producer = FakeProducer()
    request_consumer = CommittableConsumer(_task_request())
    plan_consumer = CommittableConsumer(_project_plan_result())
    helper_consumer = CommittableConsumer(_helper_result())
    context = TaskServiceServerContext(
        dispatcher=TaskServiceDispatcher(producer=producer),
        request_consumer=request_consumer,
        project_plan_result_consumers=((TOPICS.project_plan_results, plan_consumer),),
        helper_result_consumers=((TOPICS.helper_retrieval_results, helper_consumer),),
    )

    await context.run_request_once()
    await context.run_project_plan_result_once(topic=TOPICS.project_plan_results)
    await context.run_helper_result_once(topic=TOPICS.helper_retrieval_results)

    assert request_consumer.commit_count == 1
    assert plan_consumer.commit_count == 1
    assert helper_consumer.commit_count == 1

    failing_consumer = CommittableConsumer(_project_plan_result(operation="export"))
    failing_context = TaskServiceServerContext(
        dispatcher=TaskServiceDispatcher(producer=FakeProducer()),
        request_consumer=CommittableConsumer(_task_request()),
        project_plan_result_consumers=((TOPICS.project_plan_results, failing_consumer),),
        helper_result_consumers=((TOPICS.helper_retrieval_results, CommittableConsumer(_helper_result())),),
    )

    with pytest.raises(ValueError, match="unsupported helper"):
        await failing_context.run_project_plan_result_once(topic=TOPICS.project_plan_results)

    assert failing_consumer.commit_count == 0


def _task_intake(payload: dict[str, object] | None = None) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload=payload if payload is not None else {"operation": "search", "request": {}},
    )


def _task_request() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_manager_service",
        message_type=MessageType.TASK_REQUEST,
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


def _project_plan_request() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.PROJECT_PLAN_REQUEST,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "search", "request": {}},
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


def _helper_command(*, operation: str, helper: str) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.HELPER_COMMAND,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": operation, "helper": helper, "plan": {"project_id": "p1"}},
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


def _workflow_command() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.DOMAIN_COMMAND,
        data_type="workflow_log",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "list", "request": {}},
    )


def _audit_event() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.AUDIT_EVENT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"event": "manager.request.accepted", "job_id": "job-1"},
    )
