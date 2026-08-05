"""Postgres project config repository tests (run against the shared Postgres)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from project_service.config.repository import (
    PostgresProjectConfigRepository,
    ProjectConfigNotFoundError,
)
from project_service.schemas import ProjectConfig


@pytest.fixture
async def repo(pg_dsn: str) -> PostgresProjectConfigRepository:
    repository = PostgresProjectConfigRepository(pg_dsn)
    await repository.initialize()
    async with repository._pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS projects CASCADE")
    await repository.initialize()
    yield repository
    await repository.close()


def _config(project_id: str) -> ProjectConfig:
    return ProjectConfig(
        project_id=project_id,
        project_type="website",
        active_embedding_version="v1",
        embedding_model="bge-base",
        reranker_model="none",
        chunker_config={"chunk_size": 512},
        retrieval_config={"mode": "dense"},
        cache_config={"ttl": 60},
    )


@pytest.mark.asyncio
async def test_upsert_and_get_roundtrip(repo) -> None:
    await repo.upsert_project(_config("p1"))
    config = await repo.get_project_config("p1")
    assert config.project_id == "p1"
    assert config.project_type == "website"
    assert config.chunker_config == {"chunk_size": 512}
    assert config.retrieval_config == {"mode": "dense"}
    assert config.cache_config == {"ttl": 60}
    assert await repo.get_project_type("p1") == "website"


@pytest.mark.asyncio
async def test_upsert_replaces_existing(repo) -> None:
    await repo.upsert_project(_config("p1"))
    updated = replace(_config("p1"), active_embedding_version="v2")
    await repo.upsert_project(updated)
    config = await repo.get_project_config("p1")
    assert config.active_embedding_version == "v2"


@pytest.mark.asyncio
async def test_get_missing_raises(repo) -> None:
    with pytest.raises(ProjectConfigNotFoundError):
        await repo.get_project_config("missing")


@pytest.mark.asyncio
async def test_set_active_embedding_version(repo) -> None:
    await repo.upsert_project(_config("p1"))
    await repo.set_active_embedding_version("p1", "v9")
    assert (await repo.get_project_config("p1")).active_embedding_version == "v9"
    with pytest.raises(ProjectConfigNotFoundError):
        await repo.set_active_embedding_version("missing", "v9")
    with pytest.raises(ValueError):
        await repo.set_active_embedding_version("p1", "  ")


@pytest.mark.asyncio
async def test_initialize_is_idempotent(repo) -> None:
    await repo.upsert_project(_config("p2"))
    await repo.initialize()
    assert (await repo.get_project_config("p2")).project_id == "p2"
