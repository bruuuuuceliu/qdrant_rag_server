"""Database-node worker tests."""

from __future__ import annotations

import pytest

from db_node import DbNodeSettings
from db_node.worker import create_worker_context


@pytest.mark.asyncio
async def test_create_db_worker_context_wires_service(pg_dsn: str) -> None:
    settings = DbNodeSettings(db_url=pg_dsn)
    from db_node import DbNodeService

    service = DbNodeService(pg_dsn)
    await service.initialize()
    async with service._pool.connection() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS db_node_health_checks, db_node_allocations,"
            " db_node_schema_versions, db_node_databases CASCADE"
        )
    await service.close()

    context = await create_worker_context(settings=settings)

    assert context.settings is settings
    assert context.service.db_url == pg_dsn
    health = await context.health()
    assert health.ready is True
    assert health.dependencies == {"postgres": True}
    assert health.details["database_count"] == 0
    await context.shutdown()
