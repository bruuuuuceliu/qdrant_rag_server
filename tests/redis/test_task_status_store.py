"""Task status store tests."""

from __future__ import annotations

import pytest

from redis_status_node import InMemoryTaskStatusStore, RedisStatusSettings, TaskStatusRecord
from redis_status_node.client import RedisTaskStatusStore


@pytest.mark.asyncio
async def test_in_memory_task_status_store_records_status_and_ttl() -> None:
    store = InMemoryTaskStatusStore()
    record = TaskStatusRecord(
        task_id="task-1",
        status="completed",
        correlation_id="corr-1",
        data_type="project_document",
        operation="search",
        result={"hits": []},
    )

    await store.set_status(record, ttl_seconds=60)

    assert await store.get_status("task-1") == record
    assert store.ttls["task-1"] == 60


def test_task_status_record_round_trips_mapping() -> None:
    record = TaskStatusRecord(task_id="task-1", status="running", result={"step": 1})

    assert TaskStatusRecord.from_mapping(record.to_mapping()) == record


def test_redis_status_settings_rejects_blank_task_key() -> None:
    settings = RedisStatusSettings()

    with pytest.raises(ValueError, match="task_id"):
        settings.task_key("")


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def ping(self) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return self.expirations.get(key, -1)


@pytest.mark.asyncio
async def test_redis_task_status_store_exposes_ping_and_ttl() -> None:
    client = FakeRedisClient()
    store = RedisTaskStatusStore(settings=RedisStatusSettings(), client=client)
    record = TaskStatusRecord(task_id="task-1", status="completed")

    await store.set_status(record, ttl_seconds=30)

    assert await store.ping() is True
    assert await store.ttl("task-1") == 30
