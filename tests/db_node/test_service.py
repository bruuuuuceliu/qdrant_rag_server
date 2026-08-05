"""Database-node service tests (Postgres-backed)."""

from __future__ import annotations

import pytest

from db_node import DbNodeService


@pytest.fixture
async def service(pg_dsn: str) -> DbNodeService:
    svc = DbNodeService(pg_dsn)
    await svc.initialize()
    async with svc._pool.connection() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS db_node_health_checks, db_node_allocations,"
            " db_node_schema_versions, db_node_databases CASCADE"
        )
    svc._initialized = False
    await svc.initialize()
    yield svc
    await svc.close()


@pytest.mark.asyncio
async def test_db_node_service_initializes_control_plane_tables(service) -> None:
    async with service._pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                "  AND tablename LIKE 'db_node_%'"
            )
        ).fetchall()
    tables = {row["tablename"] for row in rows}
    assert "db_node_databases" in tables
    assert "db_node_schema_versions" in tables
    assert "db_node_allocations" in tables
    assert "db_node_health_checks" in tables


@pytest.mark.asyncio
async def test_allocate_database_records_owner_schema_and_allocation_history(service) -> None:
    first = await service.allocate_database(
        owner_service="project_service",
        database_name="project_config",
        purpose="project configuration",
    )
    second = await service.allocate_database(
        owner_service="project_service",
        database_name="project_config",
        purpose="project configuration",
        schema_version=2,
    )
    records = await service.list_databases(owner_service="project_service")
    allocations = await service.list_allocations("project_config")

    assert first == "project_config"
    assert second == first
    assert len(records) == 1
    assert records[0].database_name == "project_config"
    assert records[0].owner_service == "project_service"
    assert records[0].target_schema == "project_config"
    assert records[0].schema_version == 2
    assert len(allocations) == 2
    assert allocations[0].resolved_schema == first


@pytest.mark.asyncio
async def test_allocate_database_rejects_cross_owner_reuse(service) -> None:
    await service.allocate_database(
        owner_service="project_service",
        database_name="project_config",
        purpose="project configuration",
    )

    with pytest.raises(ValueError, match="already owned"):
        await service.allocate_database(
            owner_service="workflow_log_service",
            database_name="project_config",
            purpose="workflow state",
        )


@pytest.mark.asyncio
async def test_allocate_database_rejects_unsafe_names(service) -> None:
    with pytest.raises(ValueError, match="path separators"):
        await service.allocate_database(
            owner_service="project_service",
            database_name="/tmp/project",
            purpose="project configuration",
        )
    with pytest.raises(ValueError, match="path separators"):
        await service.allocate_database(
            owner_service="../project_service",
            database_name="project_config",
            purpose="project configuration",
        )


@pytest.mark.asyncio
async def test_schema_versions_upsert_for_allocated_database(service) -> None:
    await service.allocate_database(
        owner_service="task_service",
        database_name="task_service_state",
        purpose="task service execution state",
    )

    first = await service.record_schema_version(
        owner_service="task_service",
        database_name="task_service_state",
        schema_name="task_service_execution_state",
        version=1,
        checksum="a",
    )
    second = await service.record_schema_version(
        owner_service="task_service",
        database_name="task_service_state",
        schema_name="task_service_execution_state",
        version=2,
        checksum="b",
    )

    assert first.version == 1
    assert second.version == 2
    assert second.checksum == "b"


@pytest.mark.asyncio
async def test_health_checks_append_and_list_latest_first(service) -> None:
    await service.allocate_database(
        owner_service="workflow_log_service",
        database_name="workflow_log",
        purpose="workflow log",
    )

    failed = await service.record_health_check(
        owner_service="workflow_log_service",
        database_name="workflow_log",
        ok=False,
        error="locked",
    )
    ok = await service.record_health_check(
        owner_service="workflow_log_service",
        database_name="workflow_log",
        ok=True,
    )
    checks = await service.latest_health_checks("workflow_log")

    assert failed.ok is False
    assert ok.ok is True
    assert checks[0].check_id == ok.check_id
    assert checks[1].error == "locked"
