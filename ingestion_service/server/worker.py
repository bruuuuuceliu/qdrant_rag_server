"""Standalone ingestion worker server."""

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
from shared.queue import LocalQueueBroker, QueueBroker, SQLiteQueueBroker


@dataclass(slots=True)
class IngestionWorkerServerContext:
    ingestion_app: IngestionAppContext
    queue: QueueBroker
    ingestion_settings: IngestionSettings

    async def shutdown(self) -> None:
        await self.ingestion_app.shutdown()


async def create_worker_server(
    settings: AppSettings | None = None,
    *,
    ingestion_settings: IngestionSettings | None = None,
    queue: QueueBroker | None = None,
    retrieval_queue: QueueBroker | None = None,
) -> IngestionWorkerServerContext:
    ingestion_settings = ingestion_settings or load_ingestion_settings(dict(os.environ))
    queue = queue or _build_queue(ingestion_settings)
    if retrieval_queue is None:
        if not ingestion_settings.retrieval_index_enabled:
            raise ValueError("INGESTION_RETRIEVAL_INDEX_ENABLED must be true")
        retrieval_queue = _build_retrieval_queue(ingestion_settings)
    jobs = SQLiteIngestionJobRepository(ingestion_settings.job_db_path)
    await jobs.initialize()
    ingestion_app = await create_ingestion_app(
        queue=queue,
        jobs=jobs,
        ingestion_service=IngestionService(),
        retrieval_queue=retrieval_queue,
        retrieval_index_topic=ingestion_settings.retrieval_index_topic,
        retrieval_index_response_timeout=(
            ingestion_settings.retrieval_index_response_timeout
        ),
        enabled=ingestion_settings.enabled,
        topic=ingestion_settings.request_topic,
    )
    return IngestionWorkerServerContext(
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


def _build_retrieval_queue(settings: IngestionSettings) -> QueueBroker:
    broker = settings.retrieval_index_queue_broker.strip().lower()
    if broker == "local":
        return LocalQueueBroker(maxsize=settings.retrieval_index_queue_maxsize)
    if broker == "sqlite":
        return SQLiteQueueBroker(
            settings.retrieval_index_queue_db_path,
            maxsize=settings.retrieval_index_queue_maxsize,
        )
    raise ValueError(
        "INGESTION_RETRIEVAL_INDEX_QUEUE_BROKER must be one of: sqlite, local"
    )


if __name__ == "__main__":
    main()
