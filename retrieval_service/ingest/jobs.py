"""Reusable ingest job status repositories."""

from __future__ import annotations

import time
from typing import Any, Protocol

from retrieval_service.core.schemas import JobStatus


class IngestJobStatusRepository(Protocol):
    async def create(self, job: Any) -> None:
        ...

    async def get(self, job_id: str) -> Any | None:
        ...

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> Any | None:
        ...


class MemoryIngestJobStatusRepository:
    """In-memory ingest status store for tests and local development."""

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}

    async def create(self, job: Any) -> None:
        self.records[job.job_id] = job

    async def get(self, job_id: str) -> Any | None:
        return self.records.get(job_id)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> Any | None:
        job = self.records.get(job_id)
        if job is None:
            return None
        job.status = status
        job.error = error
        job.updated_at = time.time()
        return job

