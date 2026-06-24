"""Storage helper node process entrypoint."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from broker_service import BrokerSettings
from shared.runtime_health import RuntimeHealth
from storage_node.config import StorageNodeSettings
from storage_node.helper_app import StorageHelperServerContext, create_helper_app
from storage_node.service import FilesystemStorageService


@dataclass(slots=True)
class StorageWorkerContext:
    settings: StorageNodeSettings
    storage: FilesystemStorageService
    helper_app: StorageHelperServerContext

    async def shutdown(self) -> None:
        await self.helper_app.stop()

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            service=self.settings.service_name,
            ready=True,
            dependencies={"storage_root": True, "broker_helper": self.helper_app is not None},
            details={
                "storage_root": str(self.storage._root),
                "command_topic": self.settings.command_topic,
            },
        )


async def create_worker_context(
    *,
    settings: StorageNodeSettings | None = None,
    broker_settings: BrokerSettings | None = None,
) -> StorageWorkerContext:
    settings = settings or StorageNodeSettings.from_values(dict(os.environ))
    storage = FilesystemStorageService(root=settings.storage_root)
    helper_app = create_helper_app(
        storage=storage,
        broker_settings=broker_settings,
        service_name=settings.service_name,
        command_topic=settings.command_topic,
    )
    return StorageWorkerContext(
        settings=settings,
        storage=storage,
        helper_app=helper_app,
    )


async def serve_forever() -> None:
    context = await create_worker_context()
    context.helper_app.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await context.shutdown()


def main() -> None:
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
