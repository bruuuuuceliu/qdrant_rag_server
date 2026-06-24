"""Broker factory tests."""

from __future__ import annotations

import pytest

import broker_service.factory as factory
from broker_service import BrokerSettings


class FakeProducer:
    def __init__(self, settings: BrokerSettings) -> None:
        self.settings = settings


class FakeConsumer:
    def __init__(self, settings: BrokerSettings, topic: str, group_id: str) -> None:
        self.settings = settings
        self.topic = topic
        self.group_id = group_id


def test_create_redpanda_bus_without_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "RedpandaProducer", FakeProducer)

    bus = factory.create_redpanda_bus(BrokerSettings(client_id="test"))

    assert isinstance(bus.producer, FakeProducer)
    assert bus.consumer is None


def test_create_redpanda_bus_with_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "RedpandaProducer", FakeProducer)
    monkeypatch.setattr(factory, "RedpandaConsumer", FakeConsumer)

    bus = factory.create_redpanda_bus(
        BrokerSettings(client_id="test"),
        topic="task.intake",
        group_id="task-manager",
    )

    assert isinstance(bus.producer, FakeProducer)
    assert isinstance(bus.consumer, FakeConsumer)
    assert bus.consumer_topic == "task.intake"
    assert bus.consumer.topic == "task.intake"
    assert bus.consumer.group_id == "task-manager"


def test_create_redpanda_bus_requires_group_id_with_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "RedpandaProducer", FakeProducer)

    with pytest.raises(ValueError, match="group_id"):
        factory.create_redpanda_bus(BrokerSettings(), topic="task.intake")
