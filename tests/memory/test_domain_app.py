"""Memory domain-app composition-root tests (mirror tests/workflow_log)."""

from __future__ import annotations

import pytest

from memory_service.domain_app import (
    create_default_domain_app,
    create_domain_app,
)
from memory_service.repository import SQLiteMemoryRepository


@pytest.mark.asyncio
async def test_create_default_domain_app_wires_fake_modes(tmp_path) -> None:
    """Fake modes build a runnable composition root with no broker required."""
    from memory_service.config import MemoryServiceSettings

    settings = MemoryServiceSettings(
        db_path=tmp_path / "memory.db",
        identity_mode="fake",
        index_mode="fake",
        search_mode="fake",
    )
    app = await create_default_domain_app(settings=settings)
    assert app.handler is not None
    assert app.consumer is not None
    assert app.identity_consumer is not None
    assert app.retrieval_consumer is not None
    await app.stop()


@pytest.mark.asyncio
async def test_create_domain_app_accepts_sqlite_repository(tmp_path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "memory.db")
    await repository.initialize()

    app = create_domain_app(repository=repository)

    assert app.handler is not None
    await app.stop()
