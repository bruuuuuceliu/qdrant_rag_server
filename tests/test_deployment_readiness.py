"""Deployment readiness tests."""

from __future__ import annotations

import pytest

import deployment.composition.readiness as readiness
from broker_service import BrokerSettings
from redis_status_node import RedisStatusSettings


class FakeAdmin:
    def __init__(self, settings: BrokerSettings) -> None:
        self.settings = settings
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class FakeStore:
    def __init__(self, *, settings: RedisStatusSettings) -> None:
        self.settings = settings
        self.client = self

    async def ping(self) -> bool:
        return True

    async def set_status(self, record, ttl_seconds: int | None = None) -> None:
        self.ttl_seconds = ttl_seconds

    async def ttl(self, task_id: str) -> int:
        return int(self.ttl_seconds or 0)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_broker_readiness_uses_required_topic_health(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_broker_health(admin, **kwargs):
        captured["started"] = admin.started
        return {"ok": True, "topics": ["task.intake"]}

    monkeypatch.setattr(readiness, "create_redpanda_admin", FakeAdmin)
    monkeypatch.setattr(readiness, "broker_health", fake_broker_health)

    check = await readiness.check_broker({"BROKER_CLIENT_ID": "ready-test"})

    assert check.ready is True
    assert check.details["topics"] == ["task.intake"]
    assert captured["started"] is True


@pytest.mark.asyncio
async def test_broker_readiness_reports_lag_failure_as_degraded_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_broker_health(admin, **kwargs):
        if kwargs.get("lag_targets"):
            raise RuntimeError("lag unavailable")
        return {"ok": True, "topics": ["task.intake"]}

    monkeypatch.setattr(readiness, "create_redpanda_admin", FakeAdmin)
    monkeypatch.setattr(readiness, "broker_health", fake_broker_health)

    check = await readiness.check_broker(
        {
            "BROKER_CLIENT_ID": "ready-test",
            "BROKER_LAG_TARGETS": "task_manager:task.intake",
        }
    )

    assert check.ready is True
    assert check.details["lag_error"] == "lag unavailable"
    assert check.details["lag_target_count"] == 1


@pytest.mark.asyncio
async def test_redis_readiness_requires_ping_and_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "RedisTaskStatusStore", FakeStore)

    check = await readiness.check_redis({"REDIS_TASK_STATUS_URL": "redis://redis:6379/0"})

    assert check.ready is True
    assert check.details["ttl"] == 60


@pytest.mark.asyncio
async def test_owned_storage_and_postgres_readiness(tmp_path, pg_dsn: str) -> None:
    values = {
        "STORAGE_NODE_ROOT": str(tmp_path / "storage"),
        "RAG_POSTGRES_URL": pg_dsn,
    }

    storage = await readiness.check_storage(values)
    postgres = await readiness.check_postgres(values)

    assert storage.ready is True
    assert postgres.ready is True
    assert postgres.details["target_schema"] == "readiness"
    assert postgres.details["database_count"] >= 1


@pytest.mark.asyncio
async def test_memory_readiness_requires_signing_key_and_reachable_db(pg_dsn: str) -> None:
    values = {
        "RAG_POSTGRES_URL": pg_dsn,
        "MEMORY_IDENTITY_MODE": "broker",
        "MEMORY_INDEX_MODE": "broker",
        "MEMORY_SEARCH_MODE": "broker",
        "SERVICE_AUTH_SIGNING_KEY": "local-dev-signing-key",
        "SERVICE_AUTH_TOKEN_ISSUER": "simple-agent-local",
        "SERVICE_AUTH_TOKEN_AUDIENCE": "simple-agent-internal",
    }

    check = await readiness.check_memory(values)

    assert check.ready is True
    assert check.details["db_url"] == pg_dsn
    assert check.details["index_mode"] == "broker"


@pytest.mark.asyncio
async def test_memory_readiness_fails_when_signing_key_missing() -> None:
    check = await readiness.check_memory(
        {
            "MEMORY_IDENTITY_MODE": "broker",
        }
    )

    assert check.ready is False
    assert "SERVICE_AUTH_SIGNING_KEY" in check.details["error"]


@pytest.mark.asyncio
async def test_retrieval_readiness_requires_reachable_postgres(pg_dsn: str) -> None:
    check = await readiness.check_retrieval({"RAG_POSTGRES_URL": pg_dsn})

    assert check.ready is True
    assert check.details["db_url"] == pg_dsn
