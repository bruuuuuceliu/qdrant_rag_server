"""Storage helper broker server tests."""

from __future__ import annotations

import asyncio

import pytest

from shared.contracts import MessageEnvelope, MessageType, TOPICS
from storage_node import StorageHelperServerContext


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
async def test_storage_helper_server_runs_once() -> None:
    handler = Handler()
    consumer = Consumer(_command())
    context = StorageHelperServerContext(handler=handler, consumer=consumer)

    await context.run_once()

    assert consumer.topic == TOPICS.helper_storage_commands
    assert handler.handled == [consumer.envelope]


@pytest.mark.asyncio
async def test_storage_helper_server_start_stop() -> None:
    context = StorageHelperServerContext(handler=Handler(), consumer=Consumer(_command()))

    context.start()
    await asyncio.sleep(0)
    await context.stop()

    assert context._task is None


def _command() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="task_service",
        message_type=MessageType.HELPER_COMMAND,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={
            "operation": "put",
            "helper": TOPICS.helper_storage_commands,
            "plan": {"key": "a.txt", "value": "hello"},
        },
    )
