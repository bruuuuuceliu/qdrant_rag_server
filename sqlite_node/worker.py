"""SQLite database-node process entrypoint."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from sqlite_node.config import SQLiteNodeSettings
from sqlite_node.service import SQLiteNodeService
from shared.runtime_health import RuntimeHealth


@dataclass(slots=True)
class SQLiteWorkerContext:
    settings: SQLiteNodeSettings
    service: SQLiteNodeService

    async def shutdown(self) -> None:
        return None

    async def health(self) -> RuntimeHealth:
        records = await self.service.list_databases()
        return RuntimeHealth(
            service=self.settings.service_name,
            ready=self.service.database_root.exists() and self.service.metadata_db_path.exists(),
            dependencies={
                "database_root": self.service.database_root.exists(),
                "metadata_db": self.service.metadata_db_path.exists(),
            },
            details={
                "database_root": str(self.service.database_root),
                "metadata_db": str(self.service.metadata_db_path),
                "database_count": len(records),
            },
        )


async def create_worker_context(
    *,
    settings: SQLiteNodeSettings | None = None,
) -> SQLiteWorkerContext:
    settings = settings or SQLiteNodeSettings.from_values(dict(os.environ))
    service = SQLiteNodeService(database_root=settings.database_root)
    await service.initialize()
    return SQLiteWorkerContext(settings=settings, service=service)


async def serve_forever() -> None:
    context = await create_worker_context()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await context.shutdown()


def main() -> None:
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
