"""Standalone ingestion worker server."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from broker_service import BrokerSettings
from configs.ingestion import IngestionSettings, load_ingestion_settings
from ingestion_service.jobs import SQLiteIngestionJobRepository
from ingestion_service.server.broker_runtime import BrokerIngestionApp
from ingestion_service.server.helper_app import IngestionHelperServerContext, create_helper_app
from ingestion_service.service import IngestionService
from shared.logging import configure_logging
from shared.ops.server import ops_server_from_env
from shared.ops.shutdown import run_service
from shared.runtime_health import RuntimeHealth


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
    ops_server = ops_server_from_env("ingestion", default_port=9006, readiness=app.health)

    async def serve() -> None:
        await app.helper_app.start_runtime()
        while True:
            await asyncio.sleep(3600)

    await run_service(serve=serve, shutdown=app.shutdown, ops_server=ops_server)


def main() -> None:
    configure_logging()
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
