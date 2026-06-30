"""Task manager app factory tests."""

from __future__ import annotations

import pytest

import task_manager_service.app as app_module
from broker_service import BrokerSettings
from redis_status_node import InMemoryTaskStatusStore
from shared.contracts import TOPICS
from task_manager_service import TaskManagerSettings


class FakeBus:
    def __init__(self, *, topic: str | None = None, group_id: str | None = None) -> None:
        self.topic = topic
        self.group_id = group_id

    async def publish(self, topic, envelope, *, key="") -> None:
        return None

    async def consume(self, topic):
        raise RuntimeError("not used")


def test_create_task_manager_app_wires_broker_buses(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_create_bus(settings: BrokerSettings, *, topic=None, group_id=None):
        return FakeBus(topic=topic, group_id=group_id)

    monkeypatch.setattr(app_module, "create_redpanda_bus", fake_create_bus)
    status_store = InMemoryTaskStatusStore()
    settings = TaskManagerSettings(service_name="tm", task_intake_topic="task.in")

    context = app_module.create_app(
        broker_settings=BrokerSettings(client_id="test"),
        settings=settings,
        status_store=status_store,
    )

    assert context.settings is settings
    assert context.dispatcher._status_store is status_store
    assert context.intake_consumer.topic == "task.in"
    assert context.intake_consumer.group_id == "tm"
    assert context.task_event_consumer.topic == TOPICS.task_events
    assert context.task_event_consumer.group_id == "tm.events"
    assert context.task_result_consumer.topic == TOPICS.task_results
    assert context.task_result_consumer.group_id == "tm.results"
