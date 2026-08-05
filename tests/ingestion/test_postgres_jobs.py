"""Postgres ingestion job repository tests (run against the shared Postgres)."""

from __future__ import annotations

import time

import pytest

from ingestion_service.jobs.postgres import PostgresIngestionJobRepository
from ingestion_service.schemas import IngestionJob
from shared.contracts import JobStatus


@pytest.fixture
async def repo(pg_dsn: str) -> PostgresIngestionJobRepository:
    repository = PostgresIngestionJobRepository(pg_dsn)
    await repository.initialize()
    async with repository._pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS ingestion_jobs CASCADE")
    await repository.initialize()
    yield repository
    await repository.close()


def _job(job_id: str, *, status: JobStatus = JobStatus.PENDING) -> IngestionJob:
    now = time.time()
    return IngestionJob(
        job_id=job_id,
        source_uri="s3://bucket/doc.pdf",
        document_id="doc-1",
        status=status,
        metadata={
            "project_id": "p1",
            "user_id": "u1",
            "kb_id": "kb1",
            "doc_id": "doc-1",
            "data_type": "project_document",
            "content_hash": "abc",
        },
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_and_get_roundtrip(repo) -> None:
    await repo.create(_job("job-1"))
    job = await repo.get("job-1")
    assert job is not None
    assert job.job_id == "job-1"
    assert job.status == JobStatus.PENDING
    assert job.metadata["project_id"] == "p1"
    assert await repo.get("missing") is None


@pytest.mark.asyncio
async def test_create_replaces_existing(repo) -> None:
    await repo.create(_job("job-1"))
    await repo.create(_job("job-1", status=JobStatus.RUNNING))
    job = await repo.get("job-1")
    assert job is not None and job.status == JobStatus.RUNNING


@pytest.mark.asyncio
async def test_update_status(repo) -> None:
    await repo.create(_job("job-1"))
    updated = await repo.update_status("job-1", JobStatus.COMPLETED)
    assert updated is not None and updated.status == JobStatus.COMPLETED
    assert await repo.update_status("missing", JobStatus.COMPLETED) is None


@pytest.mark.asyncio
async def test_update_metadata_merges(repo) -> None:
    await repo.create(_job("job-1"))
    updated = await repo.update_metadata("job-1", {"page_count": 3})
    assert updated is not None
    assert updated.metadata["page_count"] == 3
    assert updated.metadata["project_id"] == "p1"
    assert await repo.update_metadata("missing", {"x": 1}) is None


@pytest.mark.asyncio
async def test_initialize_is_idempotent(repo) -> None:
    await repo.create(_job("job-1"))
    await repo.initialize()
    assert (await repo.get("job-1")) is not None
