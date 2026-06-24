"""Standalone ingestion worker server."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from broker_service import BrokerSettings
from configs.ingestion import IngestionSettings, load_ingestion_settings
from ingestion_service.jobs import SQLiteIngestionJobRepository
from ingestion_service.server.broker_runtime import BrokerIngestionApp
from ingestion_service.server.app import IngestionAppContext, create_app as create_ingestion_app
from ingestion_service.server.helper_app import IngestionHelperServerContext, create_helper_app
from ingestion_service.service import IngestionService
from shared.runtime_health import RuntimeHealth
from shared.queue import LocalQueueBroker, QueueBroker, SQLiteQueueBroker


@dataclass(slots=True)
class IngestionWorkerServerContext:
    ingestion_app: BrokerIngestionApp
    helper_app: IngestionHelperServerContext
    ingestion_settings: IngestionSettings

    async def shutdown(self) -> None:
        await self.helper_app.stop()

    async def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            service=self.ingestion_settings.service_name,
            ready=True,
            dependencies={"jobs": True, "broker_helper": self.helper_app is not None},
            details={
                "job_db_path": str(self.ingestion_settings.job_db_path),
                "command_topic": self.ingestion_settings.command_topic,
            },
        )


async def create_worker_server(
    *,
    ingestion_settings: IngestionSettings | None = None,
    broker_settings: BrokerSettings | None = None,
) -> IngestionWorkerServerContext:
    ingestion_settings = ingestion_settings or load_ingestion_settings(dict(os.environ))
    jobs = SQLiteIngestionJobRepository(ingestion_settings.job_db_path)
    await jobs.initialize()
    ingestion_app = BrokerIngestionApp(
        jobs=jobs,
        ingestion_service=IngestionService(),
    )
    helper_app = create_helper_app(
        app=ingestion_app,
        broker_settings=broker_settings,
        service_name=ingestion_settings.service_name,
        command_topic=ingestion_settings.command_topic,
    )
    return IngestionWorkerServerContext(
        ingestion_app=ingestion_app,
        helper_app=helper_app,
        ingestion_settings=ingestion_settings,
    )


async def serve_forever() -> None:
    app = await create_worker_server()
    app.helper_app.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.shutdown()


def main() -> None:
    asyncio.run(serve_forever())


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
