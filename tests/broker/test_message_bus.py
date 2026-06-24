"""Broker message bus tests."""

from __future__ import annotations

import pytest

from broker_service import BrokerMessageBus
from shared.contracts import MessageEnvelope, MessageType, TOPICS


class Component:
    def __init__(self, *, fail_stop: bool = False) -> None:
        self.started = False
        self.stopped = False
        self.fail_stop = fail_stop
        self.published: list[tuple[str, MessageEnvelope, str]] = []
        self.envelope = _envelope()

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True
        if self.fail_stop:
            raise RuntimeError("stop failed")

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))

    async def consume(self, topic: str) -> MessageEnvelope:
        return self.envelope


@pytest.mark.asyncio
async def test_message_bus_delegates_publish_consume_and_lifecycle() -> None:
    producer = Component()
    consumer = Component()
    bus = BrokerMessageBus(producer=producer, consumer=consumer)
    envelope = _envelope()

    await bus.start()
    await bus.publish(TOPICS.task_intake, envelope, key="task-1")
    consumed = await bus.consume(TOPICS.task_intake)
    await bus.stop()

    assert producer.started is True
    assert consumer.started is True
    assert producer.stopped is True
    assert consumer.stopped is True
    assert producer.published == [(TOPICS.task_intake, envelope, "task-1")]
    assert consumed == consumer.envelope


@pytest.mark.asyncio
async def test_message_bus_requires_consumer_for_consume() -> None:
    bus = BrokerMessageBus(producer=Component())

    with pytest.raises(RuntimeError, match="no consumer"):
        await bus.consume(TOPICS.task_intake)


@pytest.mark.asyncio
async def test_message_bus_rejects_unconfigured_consumer_topic() -> None:
    bus = BrokerMessageBus(
        producer=Component(),
        consumer=Component(),
        consumer_topic=TOPICS.task_intake,
    )

    with pytest.raises(ValueError, match=TOPICS.task_intake):
        await bus.consume(TOPICS.task_results)


@pytest.mark.asyncio
async def test_message_bus_stop_attempts_both_components_when_one_fails() -> None:
    producer = Component()
    consumer = Component(fail_stop=True)
    bus = BrokerMessageBus(producer=producer, consumer=consumer)

    with pytest.raises(RuntimeError, match="stop failed"):
        await bus.stop()

    assert consumer.stopped is True
    assert producer.stopped is True


def _envelope() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
    )
