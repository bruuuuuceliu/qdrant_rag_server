"""Manager service bootstrap.

This is a compatibility composition root while the monolith is split. It starts
the existing gRPC app and exposes a `ManagerService` facade for route-aware
operations.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from configs import AppSettings, load_settings
from configs.manager import ManagerSettings, load_manager_settings
from manager_service.server.grpc import serve_grpc as serve_manager_grpc
from manager_service.routing import ManagerRouter
from manager_service.service import ManagerService
from project_service.client import (
    LocalProjectServiceClient,
    ProjectPlannedRetrievalApiClient,
    RemoteProjectServiceClient,
)
from project_service.planning import ProjectPlanningService
from project_service.server.app import AppContext as ProjectAppContext
from project_service.server.app import create_app as create_project_app
from ingestion_service.jobs import SQLiteIngestionJobRepository
from ingestion_service.server import IngestionAppContext
from ingestion_service.server import IngestionApiServerContext
from ingestion_service.server import create_api_app as create_ingestion_api_app
from ingestion_service.server import create_app as create_ingestion_app
from ingestion_service.service import IngestionService
from retrieval_service.server import RetrievalApiQueueClient
from retrieval_service.server import RetrievalApiHttpClient
from retrieval_service.server import RetrievalApiQueueAppContext
from retrieval_service.server import RetrievalApiServerContext
from retrieval_service.server import create_app as create_retrieval_api_app
from retrieval_service.server import create_queue_app as create_retrieval_queue_app
from shared.queue import LocalQueueBroker
from shared.queue import SQLiteQueueBroker


@dataclass(slots=True)
class ManagerAppContext:
    project_app: ProjectAppContext | None
    project_client: object
    retrieval_api_client: object | None
    retrieval_api_app: RetrievalApiServerContext | RetrievalApiQueueAppContext | None
    ingestion_app: IngestionAppContext | None
    ingestion_api_app: IngestionApiServerContext | None
    manager: ManagerService
    manager_settings: ManagerSettings
    manager_server: object

    @property
    def settings(self) -> AppSettings:
        if self.project_app is None:
            raise RuntimeError("settings are unavailable when project service is remote")
        return self.project_app.settings

    @property
    def server(self) -> object:
        return self.manager_server

    @property
    def ingestion_jobs(self) -> object | None:
        if self.ingestion_app is None:
            return None
        return self.ingestion_app.jobs

    async def shutdown(self) -> None:
        await self.manager_server.stop(grace=5)
        if self.ingestion_api_app is not None:
            await self.ingestion_api_app.shutdown()
        elif self.ingestion_app is not None:
            await self.ingestion_app.shutdown()
        if self.retrieval_api_app is not None:
            await self.retrieval_api_app.shutdown()
        elif self.retrieval_api_client is not None:
            shutdown_retrieval_client = getattr(self.retrieval_api_client, "shutdown", None)
            if shutdown_retrieval_client is not None:
                await shutdown_retrieval_client()
        if self.project_app is not None:
            await self.project_app.shutdown()
        else:
            shutdown_project_client = getattr(self.project_client, "shutdown", None)
            if shutdown_project_client is not None:
                await shutdown_project_client()


async def create_app(
    settings: AppSettings | None = None,
    *,
    manager_settings: ManagerSettings | None = None,
) -> ManagerAppContext:
    manager_settings = manager_settings or load_manager_settings(dict(os.environ))
    project_app: ProjectAppContext | None = None
    retrieval_api_app: RetrievalApiServerContext | RetrievalApiQueueAppContext | None = None
    retrieval_api_client = None
    project_client = None
    health_checker = None
    generation_engine = None
    project_client_mode = manager_settings.project_client_mode.strip().lower()
    if project_client_mode == "local":
        project_app = await create_project_app(settings, start_server=False)
        project_client = project_app.project_client
        health_checker = project_app.health_checker
        generation_engine = project_app.engine
    elif project_client_mode == "grpc":
        project_client = RemoteProjectServiceClient(
            target=manager_settings.project_grpc_target,
        )
    else:
        raise ValueError("MANAGER_PROJECT_CLIENT_MODE must be one of: local, grpc")
    request_broker = _build_request_broker(manager_settings)
    ingestion_app = None
    ingestion_api_app = None
    public_settings = settings or (
        project_app.settings if project_app is not None else load_settings()
    )
    if manager_settings.ingestion_worker_mode == "embedded":
        ingest_jobs = SQLiteIngestionJobRepository(public_settings.ingest_job_db_path)
        await ingest_jobs.initialize()
        ingestion_app = await create_ingestion_app(
            queue=request_broker,
            jobs=ingest_jobs,
            ingestion_service=IngestionService(),
            retrieval_queue=request_broker,
            enabled=True,
            topic=manager_settings.ingest_topic,
        )
        ingestion_api_app = await create_ingestion_api_app(ingestion_app=ingestion_app)
    elif manager_settings.ingestion_worker_mode != "external":
        raise ValueError("MANAGER_INGESTION_WORKER_MODE must be embedded or external")
    if project_app is not None:
        placement_resolver = getattr(project_app, "placement_resolver", None)
        routing_policy = getattr(project_app, "routing_policy", None)
        retrieval_mode = manager_settings.retrieval_client_mode.strip().lower()
        if retrieval_mode == "local":
            retrieval_api_app = await create_retrieval_api_app(
                retrieval_service=project_app.engine.retrieval_service,
            )
            retrieval_api_client = retrieval_api_app
        elif retrieval_mode == "queue":
            retrieval_api_app = await create_retrieval_queue_app(
                queue=request_broker,
                retrieval_service=project_app.engine.retrieval_service,
                enabled=True,
                topic=manager_settings.retrieval_topic,
            )
            retrieval_api_client = RetrievalApiQueueClient(
                queue=request_broker,
                topic=manager_settings.retrieval_topic,
                response_timeout=manager_settings.retrieval_response_timeout,
            )
        elif retrieval_mode == "http":
            retrieval_api_client = RetrievalApiHttpClient(
                base_url=manager_settings.retrieval_http_base_url,
                timeout=manager_settings.retrieval_http_timeout,
            )
        else:
            raise ValueError(
                "MANAGER_RETRIEVAL_CLIENT_MODE must be one of: local, queue, http"
            )
        project_client = LocalProjectServiceClient(
            gateway=project_app.gateway,
            engine=project_app.engine,
            retrieval_executor=ProjectPlannedRetrievalApiClient(
                planning=ProjectPlanningService(
                    gateway=project_app.gateway,
                    placement_resolver=placement_resolver,
                    routing_policy=routing_policy,
                ),
                retrieval_api=retrieval_api_client,
            ),
            planning=ProjectPlanningService(
                gateway=project_app.gateway,
                placement_resolver=placement_resolver,
                routing_policy=routing_policy,
            ),
        )
    manager = ManagerService(
        project_documents=project_client,
        ingest_topic=manager_settings.ingest_topic,
        router=ManagerRouter(
            ingest_topic=manager_settings.ingest_topic,
            workflow_topic=manager_settings.workflow_topic,
        ),
        allow_direct_project_client=True,
    )
    manager_server = await serve_manager_grpc(
        manager=manager,
        generation_engine=generation_engine,
        health_checker=health_checker,
        port=public_settings.grpc_port,
    )
    return ManagerAppContext(
        project_app=project_app,
        project_client=project_client,
        retrieval_api_app=retrieval_api_app,
        retrieval_api_client=retrieval_api_client,
        ingestion_app=ingestion_app,
        ingestion_api_app=ingestion_api_app,
        manager=manager,
        manager_settings=manager_settings,
        manager_server=manager_server,
    )


def _build_request_broker(settings: ManagerSettings):
    broker = settings.queue_broker.strip().lower()
    if broker == "local":
        return LocalQueueBroker(maxsize=settings.local_queue_maxsize)
    if broker == "sqlite":
        return SQLiteQueueBroker(
            settings.queue_db_path,
            maxsize=settings.local_queue_maxsize,
        )
    raise ValueError("MANAGER_QUEUE_BROKER must be one of: local, sqlite")


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
