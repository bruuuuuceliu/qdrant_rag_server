"""Workflow-log domain server context tests."""

from __future__ import annotations

import asyncio

import pytest

from shared.contracts import MessageEnvelope, MessageType, TOPICS
from workflow_log_service import WorkflowLogDomainServerContext


class Handler:
    def __init__(self) -> None:
        self.handled: list[MessageEnvelope] = []

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        self.handled.append(envelope)
        return envelope


class Consumer:
    def __init__(self, envelope: MessageEnvelope) -> None:
        self.envelope = envelope
        self.topic = ""
        self.consumed = False

    async def consume(self, topic: str) -> MessageEnvelope:
        self.topic = topic
        if self.consumed:
            await asyncio.Event().wait()
        self.consumed = True
        return self.envelope


@pytest.mark.asyncio
async def test_workflow_log_domain_server_runs_once() -> None:
    handler = Handler()
    consumer = Consumer(_command())
    context = WorkflowLogDomainServerContext(handler=handler, consumer=consumer)

    await context.run_once()

    assert consumer.topic == TOPICS.domain_workflow_log_commands
    assert handler.handled == [consumer.envelope]


@pytest.mark.asyncio
async def test_workflow_log_domain_server_runs_audit_once() -> None:
    handler = Handler()
    consumer = Consumer(_command())
    audit_consumer = Consumer(_audit_event())
    context = WorkflowLogDomainServerContext(
        handler=handler,
        consumer=consumer,
        audit_consumer=audit_consumer,
    )

    await context.run_audit_once()

    assert audit_consumer.topic == TOPICS.audit_events
    assert handler.handled == [audit_consumer.envelope]


@pytest.mark.asyncio
async def test_workflow_log_domain_server_start_stop() -> None:
    context = WorkflowLogDomainServerContext(
        handler=Handler(),
        consumer=Consumer(_command()),
        audit_consumer=Consumer(_audit_event()),
    )

    context.start()
    await asyncio.sleep(0)
    await context.stop()

    assert context._task is None
    assert context._audit_task is None


def _command() -> MessageEnvelope:
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
