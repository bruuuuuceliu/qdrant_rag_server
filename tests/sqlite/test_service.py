"""SQLite database-node service tests."""

from __future__ import annotations

import pytest

from sqlite_node import SQLiteNodeService


@pytest.mark.asyncio
async def test_sqlite_node_service_initializes_root_and_builds_db_paths(tmp_path) -> None:
    service = SQLiteNodeService(database_root=tmp_path / "dbs")

    await service.initialize()

    assert service.database_root.exists()
    assert service.metadata_db_path.exists()
    assert service.database_path("project_config") == tmp_path / "dbs" / "project_config.db"
    assert service.database_path("workflow.db") == tmp_path / "dbs" / "workflow.db"


def test_sqlite_node_service_rejects_nested_database_names(tmp_path) -> None:
    service = SQLiteNodeService(database_root=tmp_path)

    with pytest.raises(ValueError, match="file name"):
        service.database_path("../outside.db")


@pytest.mark.asyncio
async def test_sqlite_node_service_initializes_control_plane_tables(tmp_path) -> None:
    service = SQLiteNodeService(database_root=tmp_path / "dbs")

    await service.initialize()

    with service._connect_metadata() as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "db_node_databases" in tables
    assert "db_node_schema_versions" in tables
    assert "db_node_allocations" in tables
    assert "db_node_health_checks" in tables


@pytest.mark.asyncio
async def test_allocate_database_records_owner_path_and_allocation_history(tmp_path) -> None:
    service = SQLiteNodeService(database_root=tmp_path / "dbs")

    first = await service.allocate_database(
        owner_service="project_service",
        database_name="project_config",
        purpose="project configuration",
    )
    second = await service.allocate_database(
        owner_service="project_service",
        database_name="project_config.db",
        purpose="project configuration",
        schema_version=2,
    )
    records = await service.list_databases(owner_service="project_service")
    allocations = await service.list_allocations("project_config")

    assert first == tmp_path / "dbs" / "project_config.db"
    assert second == first
    assert len(records) == 1
    assert records[0].database_name == "project_config"
    assert records[0].owner_service == "project_service"
    assert records[0].relative_path == "project_config.db"
    assert records[0].schema_version == 2
    assert len(allocations) == 2
    assert allocations[0].resolved_path == str(first)


@pytest.mark.asyncio
async def test_allocate_database_rejects_cross_owner_reuse(tmp_path) -> None:
    service = SQLiteNodeService(database_root=tmp_path / "dbs")
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
async def test_allocate_database_rejects_unsafe_names(tmp_path) -> None:
    service = SQLiteNodeService(database_root=tmp_path / "dbs")

    with pytest.raises(ValueError, match="file name"):
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
async def test_schema_versions_upsert_for_allocated_database(tmp_path) -> None:
    service = SQLiteNodeService(database_root=tmp_path / "dbs")
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
async def test_health_checks_append_and_list_latest_first(tmp_path) -> None:
    service = SQLiteNodeService(database_root=tmp_path / "dbs")
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
