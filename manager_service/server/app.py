"""Manager service bootstrap.

This module starts only the manager server. Broker producer and Redis
task-status dependencies must be provided by the runtime composition layer.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from configs import AppSettings, load_settings
from configs.manager import ManagerSettings, load_manager_settings
from manager_service.routing import ManagerRouter
from manager_service.server.grpc import serve_grpc as serve_manager_grpc
from manager_service.service import ManagerService
from shared.contracts import MessageProducer, TaskStatusStore


@dataclass(slots=True)
class ManagerAppContext:
    task_producer: MessageProducer | None
    task_status_store: TaskStatusStore | None
    manager: ManagerService
    manager_settings: ManagerSettings
    manager_server: Any

    @property
    def server(self) -> Any:
        return self.manager_server

    async def shutdown(self) -> None:
        await self.manager_server.stop(grace=5)
        stop_task_producer = getattr(self.task_producer, "stop", None)
        if stop_task_producer is not None:
            await stop_task_producer()
        close_status = getattr(getattr(self.task_status_store, "client", None), "aclose", None)
        if close_status is not None:
            await close_status()


async def create_app(
    settings: AppSettings | None = None,
    *,
    task_producer: MessageProducer | None = None,
    task_status_store: TaskStatusStore | None = None,
    manager_settings: ManagerSettings | None = None,
    health_checker: Any = None,
) -> ManagerAppContext:
    """Create the manager server with injected broker/status dependencies."""

    if task_producer is None:
        raise ValueError("manager server requires a task producer")
    settings = settings or load_settings()
    manager_settings = manager_settings or load_manager_settings(dict(os.environ))
    start_task_producer = getattr(task_producer, "start", None)
    if start_task_producer is not None:
        await start_task_producer()
    manager = ManagerService(
        task_producer=task_producer,
        task_status_store=task_status_store,
        task_intake_topic=manager_settings.task_intake_topic,
        router=ManagerRouter(),
    )
    manager_server = await serve_manager_grpc(
        manager=manager,
        health_checker=health_checker,
        port=settings.grpc_port,
    )
    return ManagerAppContext(
        task_producer=task_producer,
        task_status_store=task_status_store,
        manager=manager,
        manager_settings=manager_settings,
        manager_server=manager_server,
    )


async def serve_forever(
    settings: AppSettings | None = None,
    *,
    task_producer: MessageProducer | None = None,
    task_status_store: TaskStatusStore | None = None,
    manager_settings: ManagerSettings | None = None,
) -> None:
    app = await create_app(
        settings,
        task_producer=task_producer,
        task_status_store=task_status_store,
        manager_settings=manager_settings,
    )
    try:
        await app.server.wait_for_termination()
    finally:
        await app.shutdown()


def main() -> None:
    raise SystemExit(
        "manager_service.server.app requires injected broker dependencies. "
        "Start the manager with python -m manager_service.worker or from a "
        "deployment composition layer."
    )


if __name__ == "__main__":
    main()
