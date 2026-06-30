"""Project domain app factory tests."""

from __future__ import annotations

import pytest

import project_service.domain_app as domain_app
from broker_service import BrokerSettings


class FakeBus:
    def __init__(self, *, topic: str | None = None, group_id: str | None = None) -> None:
        self.topic = topic
        self.group_id = group_id

    async def publish(self, topic, envelope, *, key="") -> None:
        return None

    async def consume(self, topic):
        raise RuntimeError("not used")


def test_project_domain_settings_loads_owned_config_values() -> None:
    settings = domain_app.ProjectDomainSettings.from_values(
        {
            "PROJECT_SERVICE_NAME": "project-a",
            "PROJECT_PLAN_REQUEST_TOPIC": "project.commands",
            "PROJECT_PLAN_RESULT_TOPIC": "project.results",
            "PROJECT_CONFIG_DB_PATH": "/data/project.db",
            "PROJECT_MAX_PER_PROJECT": "12",
            "PROJECT_MAX_PER_USER": "3",
        }
    )

    assert settings.service_name == "project-a"
    assert settings.command_topic == "project.commands"
    assert settings.result_topic == "project.results"
    assert settings.config_db_path == "/data/project.db"
    assert settings.max_per_project == 12
    assert settings.max_per_user == 3


@pytest.mark.asyncio
async def test_create_default_project_domain_app_builds_planning_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str | None, str | None]] = []

    def fake_create_bus(settings: BrokerSettings, *, topic=None, group_id=None):
        calls.append((topic, group_id))
        return FakeBus(topic=topic, group_id=group_id)

    monkeypatch.setattr(domain_app, "create_redpanda_bus", fake_create_bus)
    settings = domain_app.ProjectDomainSettings(
        service_name="project-a",
        command_topic="project.commands",
        result_topic="project.results",
        config_db_path=":memory:",
    )

    context = await domain_app.create_default_domain_app(
        settings=settings,
        broker_settings=BrokerSettings(client_id="project-test"),
    )

    assert context.command_topic == "project.commands"
    assert calls == [(None, None), ("project.commands", "project-a")]
