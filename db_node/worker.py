"""Database-node process entrypoint."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from db_node.config import DbNodeSettings
from db_node.service import DbNodeService
from shared.logging import configure_logging
from shared.ops.server import ops_server_from_env
from shared.ops.shutdown import run_service
from shared.postgres import pg_dsn
from shared.runtime_health import RuntimeHealth

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DbWorkerContext:
    settings: DbNodeSettings
    service: DbNodeService

    async def shutdown(self) -> None:
        await self.service.close()

    async def health(self) -> RuntimeHealth:
        records = await self.service.list_databases()
        return RuntimeHealth(
            service=self.settings.service_name,
            ready=True,
            dependencies={
                "postgres": True,
            },
            details={
                "database_count": len(records),
            },
        )


async def create_worker_context(
    *,
    settings: DbNodeSettings | None = None,
) -> DbWorkerContext:
    settings = settings or DbNodeSettings.from_values(dict(os.environ))
    service = DbNodeService(pg_dsn(settings.db_url))
    await service.initialize()
    return DbWorkerContext(settings=settings, service=service)


async def serve_forever() -> None:
    context = await create_worker_context()
    ops_server = ops_server_from_env("db_node", default_port=9010, readiness=context.health)

    async def serve() -> None:
        while True:
            await asyncio.sleep(3600)

    await run_service(serve=serve, shutdown=context.shutdown, ops_server=ops_server)


def main() -> None:
    configure_logging(service_name="db_node")
    logger.info("starting db_node")
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
