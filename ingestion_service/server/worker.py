"""Standalone ingestion worker server.

This process owns queued ingest consumption and connects to a project-service
client. For local extraction it can either embed the project app without its
public server or call a separately running project gRPC server.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from configs import AppSettings, load_settings
from configs.ingestion import IngestionSettings, load_ingestion_settings
from ingestion_service.jobs import SQLiteIngestionJobRepository
from ingestion_service.server.app import IngestionAppContext, create_app as create_ingestion_app
from ingestion_service.service import IngestionService
from project_service.client import RemoteProjectServiceClient
from project_service.server.app import AppContext as ProjectAppContext
from project_service.server.app import create_app as create_project_app
from shared.queue import LocalQueueBroker, QueueBroker, SQLiteQueueBroker


@dataclass(slots=True)
class IngestionWorkerServerContext:
    project_app: ProjectAppContext | None
    project_client: object
    ingestion_app: IngestionAppContext
    queue: QueueBroker
    ingestion_settings: IngestionSettings

    async def shutdown(self) -> None:
        await self.ingestion_app.shutdown()
        if self.project_app is not None:
            await self.project_app.shutdown()
        else:
            shutdown_project_client = getattr(self.project_client, "shutdown", None)
            if shutdown_project_client is not None:
                await shutdown_project_client()


async def create_worker_server(
    settings: AppSettings | None = None,
    *,
    ingestion_settings: IngestionSettings | None = None,
    queue: QueueBroker | None = None,
    retrieval_queue: QueueBroker | None = None,
) -> IngestionWorkerServerContext:
    ingestion_settings = ingestion_settings or load_ingestion_settings(dict(os.environ))
    project_app: ProjectAppContext | None = None
    project_client: object
    project_client_mode = ingestion_settings.project_client_mode.strip().lower()
    if project_client_mode == "local":
        project_app = await create_project_app(settings, start_server=False)
        project_client = project_app.project_client
    elif project_client_mode == "grpc":
        project_client = RemoteProjectServiceClient(
            target=ingestion_settings.project_grpc_target,
        )
    else:
        raise ValueError("INGESTION_PROJECT_CLIENT_MODE must be one of: local, grpc")
    queue = queue or _build_queue(ingestion_settings)
    jobs = SQLiteIngestionJobRepository(ingestion_settings.job_db_path)
    await jobs.initialize()
    ingestion_app = await create_ingestion_app(
        queue=queue,
        project_documents=project_client,
        jobs=jobs,
        ingestion_service=IngestionService(),
        retrieval_queue=retrieval_queue,
        enabled=ingestion_settings.enabled,
        topic=ingestion_settings.request_topic,
    )
    return IngestionWorkerServerContext(
        project_app=project_app,
        project_client=project_client,
        ingestion_app=ingestion_app,
        queue=queue,
        ingestion_settings=ingestion_settings,
    )


async def serve_forever(settings: AppSettings | None = None) -> None:
    app = await create_worker_server(settings)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.shutdown()


def main() -> None:
    asyncio.run(serve_forever(load_settings()))


def _build_queue(settings: IngestionSettings) -> QueueBroker:
    broker = os.environ.get("INGESTION_QUEUE_BROKER", "sqlite").strip().lower()
    if broker == "local":
        return LocalQueueBroker(maxsize=settings.queue_maxsize)
    if broker == "sqlite":
        db_path = Path(
            os.environ.get(
                "INGESTION_QUEUE_DB_PATH",
                str(Path(settings.job_db_path).with_name("ingestion_queue.db")),
            )
        )
        return SQLiteQueueBroker(db_path, maxsize=settings.queue_maxsize)
    raise ValueError("INGESTION_QUEUE_BROKER must be one of: sqlite, local")


if __name__ == "__main__":
    main()
