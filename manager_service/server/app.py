"""Manager service bootstrap.

This module starts only the manager server. Other service clients must be
provided by the runtime composition layer.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from configs import AppSettings, load_settings
from configs.manager import ManagerSettings, load_manager_settings
from manager_service.clients import ProjectDocumentClient
from manager_service.routing import ManagerRouter
from manager_service.server.grpc import serve_grpc as serve_manager_grpc
from manager_service.service import ManagerService
from shared.contracts import MessageProducer, TaskStatusStore


@dataclass(slots=True)
class ManagerAppContext:
    project_client: ProjectDocumentClient | None
    manager: ManagerService
    manager_settings: ManagerSettings
    manager_server: Any

    @property
    def server(self) -> Any:
        return self.manager_server

    async def shutdown(self) -> None:
        await self.manager_server.stop(grace=5)
        shutdown_project_client = getattr(self.project_client, "shutdown", None)
        if shutdown_project_client is not None:
            await shutdown_project_client()


async def create_app(
    settings: AppSettings | None = None,
    *,
    project_client: ProjectDocumentClient | None = None,
    task_producer: MessageProducer | None = None,
    task_status_store: TaskStatusStore | None = None,
    allow_direct_project_client: bool = False,
    manager_settings: ManagerSettings | None = None,
    generation_engine: Any = None,
    health_checker: Any = None,
) -> ManagerAppContext:
    """Create the manager server with injected service clients."""

    if project_client is None and task_producer is None:
        raise ValueError("manager server requires a project-document client or task producer")
    settings = settings or load_settings()
    manager_settings = manager_settings or load_manager_settings(dict(os.environ))
    manager = ManagerService(
        project_documents=project_client,
        task_producer=task_producer,
        task_status_store=task_status_store,
        task_intake_topic=manager_settings.task_intake_topic,
        ingest_topic=manager_settings.ingest_topic,
        router=ManagerRouter(
            ingest_topic=manager_settings.ingest_topic,
            workflow_topic=manager_settings.workflow_topic,
        ),
        allow_direct_project_client=allow_direct_project_client,
    )
    manager_server = await serve_manager_grpc(
        manager=manager,
        generation_engine=generation_engine,
        health_checker=health_checker,
        port=settings.grpc_port,
    )
    return ManagerAppContext(
        project_client=project_client,
        manager=manager,
        manager_settings=manager_settings,
        manager_server=manager_server,
    )


async def serve_forever(
    settings: AppSettings | None = None,
    *,
    project_client: ProjectDocumentClient | None = None,
    task_producer: MessageProducer | None = None,
    task_status_store: TaskStatusStore | None = None,
    manager_settings: ManagerSettings | None = None,
) -> None:
    app = await create_app(
        settings,
        project_client=project_client,
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
        "manager_service.server.app now requires injected service clients. "
        "Use local_runtime.manager_app for the temporary local compatibility "
        "composition, or start the manager from a deployment composition layer."
    )


if __name__ == "__main__":
    main()
