"""Durable SQLite ingestion job storage.

When an AsyncExecutor is injected, blocking SQLite calls run on its thread
pool. Without one (e.g. in tests), calls run synchronously on the event
loop thread — acceptable for lightweight test databases.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from ingestion_service.schemas import IngestionJob
from shared.contracts import JobStatus
from shared.executor import AsyncExecutor


class SQLiteIngestionJobRepository:
    """SQLite-backed ingestion job repository."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        executor: AsyncExecutor | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._executor = executor

    async def initialize(self) -> None:
        if self._executor is not None:
            await self._executor.run(self._initialize_sync)
        else:
            self._initialize_sync()

    async def create(self, job: IngestionJob) -> None:
        if self._executor is not None:
            await self._executor.run(self._create_sync, job)
        else:
            self._create_sync(job)

    async def get(self, job_id: str) -> IngestionJob | None:
        if self._executor is not None:
            return await self._executor.run(self._get_sync, job_id)
        return self._get_sync(job_id)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> IngestionJob | None:
        if self._executor is not None:
            return await self._executor.run(
                self._update_status_sync, job_id, status, error
            )
        return self._update_status_sync(job_id, status, error)

    async def update_metadata(
        self,
        job_id: str,
        metadata: dict[str, object],
    ) -> IngestionJob | None:
        if self._executor is not None:
            return await self._executor.run(
                self._update_metadata_sync, job_id, metadata
            )
        return self._update_metadata_sync(job_id, metadata)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kb_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    data_type TEXT NOT NULL DEFAULT 'project_document',
                    status TEXT NOT NULL,
                    error TEXT,
                    content_hash TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_project_user
                    ON ingestion_jobs(project_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_doc
                    ON ingestion_jobs(project_id, kb_id, doc_id);
                CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status
                    ON ingestion_jobs(status);
                """
            )

    def _create_sync(self, job: IngestionJob) -> None:
        metadata = dict(job.metadata)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ingestion_jobs (
                    job_id, project_id, user_id, kb_id, doc_id, source_uri,
                    data_type, status, error, content_hash, metadata_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    str(metadata.get("project_id", "")),
                    str(metadata.get("user_id", "")),
                    str(metadata.get("kb_id", "")),
                    str(metadata.get("doc_id", job.document_id)),
                    job.source_uri,
                    str(metadata.get("data_type", "project_document")),
                    str(job.status),
                    job.error,
                    str(metadata.get("content_hash", "")),
                    json.dumps(metadata, sort_keys=True),
                    job.created_at,
                    job.updated_at,
                ),
            )

    def _get_sync(self, job_id: str) -> IngestionJob | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT job_id, source_uri, doc_id, status, error, metadata_json,
                       created_at, updated_at
                  FROM ingestion_jobs
                 WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        metadata = json.loads(row["metadata_json"])
        return IngestionJob(
            job_id=row["job_id"],
            source_uri=row["source_uri"],
            document_id=row["doc_id"],
            status=JobStatus(row["status"]),
            error=row["error"],
            metadata=metadata,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _update_status_sync(
        self,
        job_id: str,
        status: JobStatus,
        error: str | None,
    ) -> IngestionJob | None:
        updated_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                   SET status = ?, error = ?, updated_at = ?
                 WHERE job_id = ?
                """,
                (str(status), error, updated_at, job_id),
            )
        return self._get_sync(job_id)

    def _update_metadata_sync(
        self,
        job_id: str,
        metadata: dict[str, object],
    ) -> IngestionJob | None:
        existing = self._get_sync(job_id)
        if existing is None:
            return None
        updated_metadata = dict(existing.metadata)
        updated_metadata.update(metadata)
        updated_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                   SET data_type = ?, content_hash = ?, metadata_json = ?, updated_at = ?
                 WHERE job_id = ?
                """,
                (
                    str(updated_metadata.get("data_type", "project_document")),
                    str(updated_metadata.get("content_hash", "")),
                    json.dumps(updated_metadata, sort_keys=True),
                    updated_at,
                    job_id,
                ),
            )
        return self._get_sync(job_id)


def content_hash_from_metadata(metadata: dict[str, Any]) -> str:
    for key in ("content_hash", "checksum", "sha256"):
        value = metadata.get(key)
        if value:
            return str(value)
    return ""
