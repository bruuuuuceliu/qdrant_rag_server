"""Deployment composition tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import deployment.composition.manager as manager_composition
import deployment.composition.task_manager as task_manager_composition
import deployment.composition.task_service as task_service_composition
from broker_service import BrokerSettings
from configs.config import AppSettings
from configs.manager import ManagerSettings
from redis_status_node import RedisStatusSettings
from task_manager_service import TaskManagerSettings
from task_service import TaskServiceSettings


@dataclass(slots=True)
class FakeRedisStore:
    settings: RedisStatusSettings


def test_task_manager_composition_wires_redis_status_store(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_create_app(*, broker_settings, settings, status_store):
        captured["broker_settings"] = broker_settings
        captured["settings"] = settings
        captured["status_store"] = status_store
        return "context"

    monkeypatch.setattr(task_manager_composition, "RedisTaskStatusStore", FakeRedisStore)
    monkeypatch.setattr(task_manager_composition, "create_task_manager_app", fake_create_app)

    context = task_manager_composition.create_task_manager_context(
        broker_settings=BrokerSettings(client_id="test"),
        task_manager_settings=TaskManagerSettings(redis_status_url="redis://redis:6379/1"),
    )

    assert context == "context"
    assert captured["broker_settings"].client_id == "test"
    assert captured["settings"].redis_status_url == "redis://redis:6379/1"
    assert captured["status_store"].settings.url == "redis://redis:6379/1"


def test_task_manager_composition_loads_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_create_app(*, broker_settings, settings, status_store):
        captured["broker_settings"] = broker_settings
        captured["settings"] = settings
        captured["status_store"] = status_store
        return "context"

    monkeypatch.setenv("REDIS_TASK_STATUS_URL", "redis://redis:6379/3")
    monkeypatch.setenv("TASK_MANAGER_TASK_INTAKE_TOPIC", "task.custom")
    monkeypatch.setenv("TASK_MANAGER_TASK_REQUEST_TOPIC", "task.requests.custom")
    monkeypatch.setattr(task_manager_composition, "RedisTaskStatusStore", FakeRedisStore)
    monkeypatch.setattr(task_manager_composition, "create_task_manager_app", fake_create_app)

    context = task_manager_composition.create_task_manager_context()

    assert context == "context"
    assert captured["broker_settings"] is None
    assert captured["settings"].task_intake_topic == "task.custom"
    assert captured["settings"].task_request_topic == "task.requests.custom"
    assert captured["status_store"].settings.url == "redis://redis:6379/3"


def test_task_service_composition_loads_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_create_app(*, broker_settings, settings):
        captured["broker_settings"] = broker_settings
        captured["settings"] = settings
        return "context"

    monkeypatch.setenv("TASK_SERVICE_STATE_DB_PATH", "/tmp/task-service-state.db")
    monkeypatch.setenv("TASK_SERVICE_TASK_REQUEST_TOPIC", "task.requests.custom")
    monkeypatch.setattr(task_service_composition, "create_task_service_app", fake_create_app)

    context = task_service_composition.create_task_service_context(
        broker_settings=BrokerSettings(client_id="task-service-test"),
    )

    assert context == "context"
    assert captured["broker_settings"].client_id == "task-service-test"
    assert captured["settings"] == TaskServiceSettings(
        task_request_topic="task.requests.custom",
        state_db_path="/tmp/task-service-state.db",
    )


@pytest.mark.asyncio
async def test_manager_composition_wires_broker_and_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_create_bus(settings: BrokerSettings):
        captured["broker_settings"] = settings
        return "bus"

    async def fake_create_manager_app(settings, *, task_producer, task_status_store, manager_settings):
        captured["settings"] = settings
        captured["task_producer"] = task_producer
        captured["task_status_store"] = task_status_store
        captured["manager_settings"] = manager_settings
        return "manager-context"

    monkeypatch.setattr(manager_composition, "create_redpanda_bus", fake_create_bus)
    monkeypatch.setattr(manager_composition, "RedisTaskStatusStore", FakeRedisStore)
    monkeypatch.setattr(manager_composition, "create_manager_app", fake_create_manager_app)

    context = await manager_composition.create_manager_context(
        _settings(),
        broker_settings=BrokerSettings(client_id="manager-test"),
        manager_settings=ManagerSettings(task_status_url="redis://redis:6379/2"),
    )

    assert context == "manager-context"
    assert captured["broker_settings"].client_id == "manager-test"
    assert captured["task_producer"] == "bus"
    assert captured["task_status_store"].settings.url == "redis://redis:6379/2"


def _settings() -> AppSettings:
    return AppSettings(
        response_cache_db_path=Path("/tmp/test-cache.db"),
        grpc_port=0,
        qdrant_url=None,
        qdrant_host="localhost",
        qdrant_port=6333,
        embedding_provider="local",
        embedding_model="test",
        embedding_device="cpu",
        embedding_api_key="",
        embedding_base_url="",
        embedding_dimension=3,
        generation_enabled=False,
    )
