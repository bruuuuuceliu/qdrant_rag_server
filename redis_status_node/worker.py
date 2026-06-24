"""Redis task-status node process entrypoint."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from redis_status_node.client import RedisTaskStatusStore
from redis_status_node.config import RedisStatusSettings
from shared.runtime_health import RuntimeHealth


@dataclass(slots=True)
class RedisStatusWorkerContext:
    settings: RedisStatusSettings
    store: RedisTaskStatusStore

    async def shutdown(self) -> None:
        client = getattr(self.store, "client", None)
        close = getattr(client, "aclose", None)
        if close is not None:
            await close()

    async def health(self) -> RuntimeHealth:
        redis_ready = False
        error = ""
        try:
            redis_ready = await self.store.ping()
        except Exception as exc:
            error = str(exc)
        return RuntimeHealth(
            service="redis_status_node",
            ready=redis_ready,
            dependencies={"redis": redis_ready},
            details={
                "url": self.settings.url,
                "key_prefix": self.settings.key_prefix,
                "error": error,
            },
        )


async def create_worker_context(
    *,
    settings: RedisStatusSettings | None = None,
    store: RedisTaskStatusStore | None = None,
) -> RedisStatusWorkerContext:
    settings = settings or RedisStatusSettings.from_values(dict(os.environ))
    return RedisStatusWorkerContext(
        settings=settings,
        store=store or RedisTaskStatusStore(settings=settings),
    )


async def serve_forever() -> None:
    context = await create_worker_context()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await context.shutdown()


def main() -> None:
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
