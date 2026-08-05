"""Memory domain-app composition-root tests (mirror tests/workflow_log)."""

from __future__ import annotations

import pytest

from memory_service.domain_app import (
    create_default_domain_app,
    create_domain_app,
)
from memory_service.repository import MemoryInMemoryRepository


@pytest.mark.asyncio
async def test_create_default_domain_app_wires_fake_modes() -> None:
    """Fake modes build a runnable composition root with no broker required."""
    from memory_service.config import MemoryServiceSettings

    settings = MemoryServiceSettings(
        identity_mode="fake",
        index_mode="fake",
        search_mode="fake",
    )
    app = await create_default_domain_app(
        settings=settings, repository=MemoryInMemoryRepository()
    )
    assert app.handler is not None
    assert app.consumer is not None
    assert app.identity_consumer is not None
    assert app.retrieval_consumer is not None
    await app.stop()


@pytest.mark.asyncio
async def test_create_domain_app_accepts_in_memory_repository() -> None:
    repository = MemoryInMemoryRepository()
    await repository.initialize()

    app = create_domain_app(repository=repository)

    assert app.handler is not None
    await app.stop()
