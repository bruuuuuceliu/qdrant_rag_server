"""Task status store contract and Redis adapter."""

from __future__ import annotations

import json
from typing import Any

from redis_status_node.config import RedisStatusSettings
from shared.contracts import TaskStatusRecord, TaskStatusStore


class InMemoryTaskStatusStore:
    """Unit-test status store; not a runtime replacement for Redis."""

    def __init__(self) -> None:
        self.records: dict[str, TaskStatusRecord] = {}
        self.ttls: dict[str, int | None] = {}

    async def set_status(self, record: TaskStatusRecord, *, ttl_seconds: int | None = None) -> None:
        self.records[record.task_id] = record
        self.ttls[record.task_id] = ttl_seconds

    async def get_status(self, task_id: str) -> TaskStatusRecord | None:
        return self.records.get(task_id)


class RedisTaskStatusStore:
    def __init__(self, *, settings: RedisStatusSettings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else _build_redis_client(settings.url)

    @property
    def client(self) -> Any:
        return self._client

    async def set_status(self, record: TaskStatusRecord, *, ttl_seconds: int | None = None) -> None:
        payload = json.dumps(record.to_mapping(), sort_keys=True)
        key = self._settings.task_key(record.task_id)
        if ttl_seconds is None:
            await self._client.set(key, payload)
        else:
            await self._client.set(key, payload, ex=ttl_seconds)

    async def get_status(self, task_id: str) -> TaskStatusRecord | None:
        value = await self._client.get(self._settings.task_key(task_id))
        if value is None:
            return None
        raw = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError("task status JSON must be an object")
        return TaskStatusRecord.from_mapping(loaded)

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def ttl(self, task_id: str) -> int:
        return int(await self._client.ttl(self._settings.task_key(task_id)))


def _build_redis_client(url: str) -> Any:
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        raise RuntimeError("redis is required for RedisTaskStatusStore") from exc
    return Redis.from_url(url)
