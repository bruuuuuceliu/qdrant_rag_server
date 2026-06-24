"""Redis task-status node worker tests."""

from __future__ import annotations

import pytest

from redis_status_node import RedisStatusSettings
from redis_status_node.worker import create_worker_context


class FakeStore:
    def __init__(self) -> None:
        self.client = FakeClient()

    async def ping(self) -> bool:
        return True


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_create_redis_status_worker_context_uses_owned_settings() -> None:
    store = FakeStore()
    settings = RedisStatusSettings(url="redis://redis:6379/2", key_prefix="task-status:")

    context = await create_worker_context(settings=settings, store=store)

    assert context.settings is settings
    assert context.store is store
    health = await context.health()
    assert health.ready is True
    assert health.details["key_prefix"] == "task-status:"
    await context.shutdown()
    assert store.client.closed is True
