"""Workflow-log domain handler tests."""

from __future__ import annotations

import pytest

from shared.contracts import MessageEnvelope, MessageType, TOPICS
from workflow_log_service import MemoryWorkflowLogRepository, WorkflowLogDomainHandler


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, MessageEnvelope, str]] = []

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


@pytest.mark.asyncio
async def test_workflow_log_domain_handler_appends_event_and_publishes_result() -> None:
    repository = MemoryWorkflowLogRepository()
    producer = FakeProducer()
    handler = WorkflowLogDomainHandler(repository=repository, producer=producer)

    result = await handler.handle(_command(operation="append"))

    entries = await repository.list_by_job("job-1")
    assert len(entries) == 1
    assert entries[0].event == "task_completed"
    assert result.message_type == MessageType.DOMAIN_RESULT
    assert result.payload["result"] == {"ok": True, "job_id": "job-1", "event": "task_completed"}
    assert producer.published == [(TOPICS.domain_workflow_log_results, result, "task-1")]


@pytest.mark.asyncio
async def test_workflow_log_domain_handler_lists_entries() -> None:
    repository = MemoryWorkflowLogRepository()
    handler = WorkflowLogDomainHandler(repository=repository)
    await handler.handle(_command(operation="append"))

    result = await handler.handle(_list_command(job_id="job-1"))

    assert result.payload["result"]["ok"] is True
    assert result.payload["result"]["entries"][0]["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_workflow_log_domain_handler_appends_audit_event_without_result_publish() -> None:
    repository = MemoryWorkflowLogRepository()
    producer = FakeProducer()
    handler = WorkflowLogDomainHandler(repository=repository, producer=producer)

    result = await handler.handle(_audit_event())

    entries = await repository.list_by_job("task-1")
    assert result.message_type == MessageType.AUDIT_EVENT
    assert len(entries) == 1
    assert entries[0].event == "manager.request.accepted"
    assert entries[0].topic == TOPICS.audit_events
    assert entries[0].key == "task-1"
    assert entries[0].headers["correlation_id"] == "corr-1"
    assert entries[0].payload["project_id"] == "p1"
    assert producer.published == []


@pytest.mark.asyncio
async def test_workflow_log_domain_handler_rejects_unknown_operation() -> None:
    handler = WorkflowLogDomainHandler(repository=MemoryWorkflowLogRepository())

    with pytest.raises(ValueError, match="unsupported"):
        await handler.handle(_list_command(operation="export"))


def _command(*, operation: str) -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.DOMAIN_COMMAND,
        data_type="workflow_log",
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "operation": operation,
            "request": {
                "event": "task_completed",
                "job_id": "job-1",
                "status": "completed",
                "project_id": "p1",
                "user_id": "u1",
            },
        },
    )


def _list_command(*, job_id: str = "", operation: str = "list") -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.DOMAIN_COMMAND,
        data_type="workflow_log",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": operation, "request": {"job_id": job_id}},
    )


def _audit_event() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.AUDIT_EVENT,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "event": "manager.request.accepted",
            "status": "accepted",
            "project_id": "p1",
            "user_id": "u1",
            "doc_id": "d1",
            "data_type": "project_document",
        },
    )
