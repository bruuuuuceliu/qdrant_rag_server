"""Manager service bootstrap.

This is a compatibility composition root while the monolith is split. It starts
the existing gRPC app and exposes a `ManagerService` facade for route-aware
operations.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from configs import AppSettings
from configs.manager import ManagerSettings, load_manager_settings
from manager_service.server.grpc import serve_grpc as serve_manager_grpc
from manager_service.routing import ManagerRouter
from manager_service.service import ManagerService
from project_service.server.app import AppContext as ProjectAppContext
from project_service.server.app import create_app as create_project_app
from ingestion_service.server import IngestionAppContext
from ingestion_service.server import create_app as create_ingestion_app
from shared.queue import LocalQueueBroker


@dataclass(slots=True)
class ManagerAppContext:
    project_app: ProjectAppContext
    ingestion_app: IngestionAppContext
    manager: ManagerService
    manager_settings: ManagerSettings
    manager_server: object

    @property
    def settings(self) -> AppSettings:
        return self.project_app.settings

    @property
    def server(self) -> object:
        return self.manager_server

    async def shutdown(self) -> None:
        await self.manager_server.stop(grace=5)
        await self.ingestion_app.shutdown()
        await self.project_app.shutdown()


async def create_app(
    settings: AppSettings | None = None,
    *,
    manager_settings: ManagerSettings | None = None,
) -> ManagerAppContext:
    project_app = await create_project_app(settings, start_server=False)
    manager_settings = manager_settings or load_manager_settings(dict(os.environ))
    request_broker = LocalQueueBroker(maxsize=manager_settings.local_queue_maxsize)
    ingestion_app = await create_ingestion_app(
        queue=request_broker,
        project_documents=project_app.project_client,
        enabled=True,
        topic=manager_settings.ingest_topic,
    )
    manager = ManagerService(
        project_documents=project_app.project_client,
        ingest_queue=request_broker,
        ingest_topic=manager_settings.ingest_topic,
        router=ManagerRouter(
            ingest_topic=manager_settings.ingest_topic,
            workflow_topic=manager_settings.workflow_topic,
        ),
    )
    manager_server = await serve_manager_grpc(
        manager=manager,
        generation_engine=project_app.engine,
        health_checker=project_app.health_checker,
        port=project_app.settings.grpc_port,
    )
    return ManagerAppContext(
        project_app=project_app,
        ingestion_app=ingestion_app,
        manager=manager,
        manager_settings=manager_settings,
        manager_server=manager_server,
    )


async def serve_forever(settings: AppSettings | None = None) -> None:
    app = await create_app(settings)
    try:
        await app.server.wait_for_termination()
    finally:
        await app.shutdown()


def main() -> None:
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
