"""Ingestion job repository protocol."""

from __future__ import annotations

import time
from typing import Protocol

from ingestion_service.schemas import IngestionJob
from retrieval_service.core.schemas import JobStatus


class IngestionJobRepository(Protocol):
    async def create(self, job: IngestionJob) -> None:
        ...

    async def get(self, job_id: str) -> IngestionJob | None:
        ...

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> IngestionJob | None:
        ...


class MemoryIngestionJobRepository:
    def __init__(self) -> None:
        self.records: dict[str, IngestionJob] = {}

    async def create(self, job: IngestionJob) -> None:
        self.records[job.job_id] = job

    async def get(self, job_id: str) -> IngestionJob | None:
        return self.records.get(job_id)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> IngestionJob | None:
        job = self.records.get(job_id)
        if job is None:
            return None
        job.status = status
        job.error = error
        job.updated_at = time.time()
        return job
