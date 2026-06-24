"""Workflow-log domain app factory tests."""

from __future__ import annotations

import pytest

import workflow_log_service.domain_app as domain_app
from broker_service import BrokerSettings


class FakeBus:
    def __init__(self, *, topic: str | None = None, group_id: str | None = None) -> None:
        self.topic = topic
        self.group_id = group_id

    async def publish(self, topic, envelope, *, key="") -> None:
        return None

    async def consume(self, topic):
        raise RuntimeError("not used")


def test_workflow_log_domain_settings_loads_owned_config_values() -> None:
    settings = domain_app.WorkflowLogDomainSettings.from_values(
        {
            "WORKFLOW_LOG_SERVICE_NAME": "workflow-a",
            "WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC": "workflow.commands",
            "WORKFLOW_LOG_DB_PATH": "/data/workflow.db",
        }
    )

    assert settings.service_name == "workflow-a"
    assert settings.command_topic == "workflow.commands"
    assert str(settings.db_path) == "/data/workflow.db"


@pytest.mark.asyncio
async def test_create_default_workflow_log_domain_app_builds_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls: list[tuple[str | None, str | None]] = []

    def fake_create_bus(settings: BrokerSettings, *, topic=None, group_id=None):
        calls.append((topic, group_id))
        return FakeBus(topic=topic, group_id=group_id)

    monkeypatch.setattr(domain_app, "create_redpanda_bus", fake_create_bus)
    settings = domain_app.WorkflowLogDomainSettings(
        service_name="workflow-a",
        command_topic="workflow.commands",
        db_path=tmp_path / "workflow.db",
    )

    context = await domain_app.create_default_domain_app(
        settings=settings,
        broker_settings=BrokerSettings(client_id="workflow-test"),
    )

    assert context.command_topic == "workflow.commands"
    assert calls == [(None, None), ("workflow.commands", "workflow-a")]
