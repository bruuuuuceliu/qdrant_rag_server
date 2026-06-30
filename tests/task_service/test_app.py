"""Task service app factory tests."""

from __future__ import annotations

import pytest

import task_service.app as app_module
from broker_service import BrokerSettings
from shared.contracts import TOPICS
from task_service import InMemoryTaskStateRepository, TaskServiceSettings


class FakeBus:
    def __init__(self, *, topic: str | None = None, group_id: str | None = None) -> None:
        self.topic = topic
        self.group_id = group_id

    async def publish(self, topic, envelope, *, key="") -> None:
        return None

    async def consume(self, topic):
        raise RuntimeError("not used")


def test_create_task_service_app_wires_broker_buses(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_create_bus(settings: BrokerSettings, *, topic=None, group_id=None):
        return FakeBus(topic=topic, group_id=group_id)

    monkeypatch.setattr(app_module, "create_redpanda_bus", fake_create_bus)
    repository = InMemoryTaskStateRepository()
    settings = TaskServiceSettings(
        service_name="task-svc",
        task_request_topic="task.requests.custom",
        project_plan_result_topic="project.plan.results.custom",
    )

    context = app_module.create_app(
        broker_settings=BrokerSettings(client_id="test"),
        settings=settings,
        state_repository=repository,
    )

    assert context.settings is settings
    assert context.dispatcher._state_repository is repository
    assert context.request_consumer.topic == "task.requests.custom"
    assert context.request_consumer.group_id == "task-svc"
    assert [(topic, consumer.group_id) for topic, consumer in context.project_plan_result_consumers] == [
        ("project.plan.results.custom", "task-svc.project_plan.0"),
    ]
    assert [topic for topic, _consumer in context.helper_result_consumers] == [
        TOPICS.helper_ingestion_results,
        TOPICS.helper_retrieval_results,
        TOPICS.helper_retrieval_index_results,
        TOPICS.helper_storage_results,
    ]
