"""Postgres workflow log repository tests (run against the shared Postgres)."""

from __future__ import annotations

import pytest

from workflow_log_service.models import WorkflowLogEntry
from workflow_log_service.repository import PostgresWorkflowLogRepository


@pytest.fixture
async def repo(pg_dsn: str) -> PostgresWorkflowLogRepository:
    repository = PostgresWorkflowLogRepository(pg_dsn)
    await repository.initialize()
    async with repository._pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS workflow_log_entries CASCADE")
    await repository.initialize()
    yield repository
    await repository.close()


def _entry(job_id: str, event: str = "job.started", created_at: float = 1.0) -> WorkflowLogEntry:
    return WorkflowLogEntry(
        event=event,
        job_id=job_id,
        status="running",
        project_id="p1",
        user_id="u1",
        kb_id="kb1",
        headers={"x": "y"},
        payload={"k": "v"},
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_append_and_list_all_preserve_order(repo) -> None:
    await repo.append(_entry("j1", created_at=1.0))
    await repo.append(_entry("j2", created_at=2.0))
    await repo.append(_entry("j1", created_at=3.0))
    entries = await repo.list_all()
    assert [e.job_id for e in entries] == ["j1", "j2", "j1"]
    assert entries[0].headers == {"x": "y"}
    assert entries[0].payload == {"k": "v"}
    assert entries[0].created_at == 1.0


@pytest.mark.asyncio
async def test_list_by_job(repo) -> None:
    await repo.append(_entry("j1", event="a"))
    await repo.append(_entry("j2", event="b"))
    await repo.append(_entry("j1", event="c"))
    entries = await repo.list_by_job("j1")
    assert [e.event for e in entries] == ["a", "c"]


@pytest.mark.asyncio
async def test_initialize_is_idempotent(repo) -> None:
    await repo.append(_entry("j1"))
    await repo.initialize()
    assert len(await repo.list_all()) == 1
