"""Workflow-log worker tests."""

from __future__ import annotations

import pytest

import workflow_log_service.worker as worker
from broker_service import BrokerSettings
from workflow_log_service import WorkflowLogDomainSettings


class DomainApp:
    def __init__(self, *, settings, broker_settings) -> None:
        self.settings = settings
        self.broker_settings = broker_settings
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_create_workflow_log_worker_context_wires_domain_app(monkeypatch, tmp_path) -> None:
    captured = {}

    async def fake_create_default_domain_app(*, settings, broker_settings):
        app = DomainApp(settings=settings, broker_settings=broker_settings)
        captured["app"] = app
        return app

    monkeypatch.setattr(worker, "create_default_domain_app", fake_create_default_domain_app)
    settings = WorkflowLogDomainSettings(
        service_name="workflow-a",
        command_topic="workflow.commands",
        audit_topic="audit.custom",
        db_path=tmp_path / "workflow.db",
    )
    broker_settings = BrokerSettings(client_id="workflow-test")

    context = await worker.create_worker_context(
        settings=settings,
        broker_settings=broker_settings,
    )

    assert context.settings is settings
    assert context.domain_app is captured["app"]
    assert context.domain_app.broker_settings is broker_settings
    health = await context.health()
    assert health.ready is True
    assert health.details["command_topic"] == "workflow.commands"
    assert health.details["audit_topic"] == "audit.custom"
    await context.shutdown()
    assert context.domain_app.stopped is True
