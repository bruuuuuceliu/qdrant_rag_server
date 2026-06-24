"""SQLite node worker tests."""

from __future__ import annotations

import pytest

from sqlite_node import SQLiteNodeSettings
from sqlite_node.worker import create_worker_context


@pytest.mark.asyncio
async def test_create_sqlite_worker_context_initializes_database_root(tmp_path) -> None:
    settings = SQLiteNodeSettings(database_root=str(tmp_path / "sqlite"))

    context = await create_worker_context(settings=settings)

    assert context.settings is settings
    assert context.service.database_root == tmp_path / "sqlite"
    assert context.service.database_root.exists()
    health = await context.health()
    assert health.ready is True
    assert health.dependencies == {"database_root": True, "metadata_db": True}
    assert health.details["database_count"] == 0
