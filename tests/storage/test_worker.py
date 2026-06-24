"""Storage node worker tests."""

from __future__ import annotations

import pytest

import storage_node.worker as worker
from broker_service import BrokerSettings
from storage_node import StorageNodeSettings


class HelperApp:
    def __init__(self, *, storage, broker_settings, service_name, command_topic) -> None:
        self.storage = storage
        self.broker_settings = broker_settings
        self.service_name = service_name
        self.command_topic = command_topic
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_create_storage_worker_context_wires_storage_helper(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_create_helper_app(*, storage, broker_settings, service_name, command_topic):
        app = HelperApp(
            storage=storage,
            broker_settings=broker_settings,
            service_name=service_name,
            command_topic=command_topic,
        )
        captured["app"] = app
        return app

    monkeypatch.setattr(worker, "create_helper_app", fake_create_helper_app)
    settings = StorageNodeSettings(storage_root=str(tmp_path), command_topic="storage.commands")
    broker_settings = BrokerSettings(client_id="storage-test")

    context = await worker.create_worker_context(
        settings=settings,
        broker_settings=broker_settings,
    )

    assert context.settings is settings
    assert context.storage._root == tmp_path
    assert context.helper_app is captured["app"]
    assert context.helper_app.service_name == "storage_node"
    assert context.helper_app.command_topic == "storage.commands"
    assert context.helper_app.broker_settings is broker_settings
    health = await context.health()
    assert health.ready is True
    assert health.details["command_topic"] == "storage.commands"
    await context.shutdown()
    assert context.helper_app.stopped is True
