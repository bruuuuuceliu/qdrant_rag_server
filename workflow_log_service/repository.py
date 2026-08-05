"""Workflow log repositories."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from shared.postgres import async_pool
from workflow_log_service.models import WorkflowLogEntry


class WorkflowLogRepository(Protocol):
    async def append(self, entry: WorkflowLogEntry) -> None:
        ...

    async def list_by_job(self, job_id: str) -> list[WorkflowLogEntry]:
        ...

    async def list_all(self) -> list[WorkflowLogEntry]:
        ...


class MemoryWorkflowLogRepository:
    """Small in-memory repository for local development and tests."""

    def __init__(self) -> None:
        self._entries: list[WorkflowLogEntry] = []

    async def initialize(self) -> None:
        return None

    async def append(self, entry: WorkflowLogEntry) -> None:
        self._entries.append(entry)

    async def list_by_job(self, job_id: str) -> list[WorkflowLogEntry]:
        return [entry for entry in self._entries if entry.job_id == job_id]

    async def list_all(self) -> list[WorkflowLogEntry]:
        return list(self._entries)


_WORKFLOW_LOG_POSTGRES_DDL = (
    """
    CREATE TABLE IF NOT EXISTS workflow_log_entries (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event TEXT NOT NULL,
        job_id TEXT NOT NULL,
        status TEXT NOT NULL,
        project_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        kb_id TEXT,
        doc_id TEXT,
        data_type TEXT,
        content_hash TEXT,
        raw_storage_key TEXT,
        error TEXT,
        topic TEXT NOT NULL,
        message_key TEXT NOT NULL,
        headers_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workflow_log_job
        ON workflow_log_entries(job_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workflow_log_project_user
        ON workflow_log_entries(project_id, user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workflow_log_event
        ON workflow_log_entries(event);
    """,
)

_WORKFLOW_LOG_SELECT = """
SELECT event, job_id, status, project_id, user_id, kb_id, doc_id,
       data_type, content_hash, raw_storage_key, error, topic,
       message_key, headers_json, payload_json, created_at
  FROM workflow_log_entries
"""


class PostgresWorkflowLogRepository:
    """Postgres-backed workflow log repository selected via ``WORKFLOW_LOG_DB_URL``."""

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self._pool = async_pool(db_url)

    async def initialize(self) -> None:
        await self._pool.open()
        await self._pool.wait()
        async with self._pool.connection() as conn:
            for statement in _WORKFLOW_LOG_POSTGRES_DDL:
                await conn.execute(statement)

    async def close(self) -> None:
        await self._pool.close()

    async def append(self, entry: WorkflowLogEntry) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO workflow_log_entries ("
                " event, job_id, status, project_id, user_id, kb_id, doc_id,"
                " data_type, content_hash, raw_storage_key, error, topic,"
                " message_key, headers_json, payload_json, created_at"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    entry.event,
                    entry.job_id,
                    entry.status,
                    entry.project_id,
                    entry.user_id,
                    entry.kb_id,
                    entry.doc_id,
                    entry.data_type,
                    entry.content_hash,
                    entry.raw_storage_key,
                    entry.error,
                    entry.topic,
                    entry.key,
                    json.dumps(entry.headers, sort_keys=True),
                    json.dumps(entry.payload, sort_keys=True),
                    entry.created_at,
                ),
            )

    async def list_by_job(self, job_id: str) -> list[WorkflowLogEntry]:
        return await self._list("WHERE job_id = %s", (job_id,))

    async def list_all(self) -> list[WorkflowLogEntry]:
        return await self._list("", ())

    async def _list(
        self,
        where: str,
        params: tuple[object, ...],
    ) -> list[WorkflowLogEntry]:
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    f"{_WORKFLOW_LOG_SELECT} {where} ORDER BY id ASC",
                    params,
                )
            ).fetchall()
        return [_entry_from_row(row) for row in rows]


def _entry_from_row(row: Mapping[str, Any]) -> WorkflowLogEntry:
    return WorkflowLogEntry(
        event=row["event"],
        job_id=row["job_id"],
        status=row["status"],
        project_id=row["project_id"],
        user_id=row["user_id"],
        kb_id=row["kb_id"] or "",
        doc_id=row["doc_id"] or "",
        data_type=row["data_type"] or "",
        content_hash=row["content_hash"] or "",
        raw_storage_key=row["raw_storage_key"] or "",
        error=row["error"] or "",
        topic=row["topic"],
        key=row["message_key"],
        headers=json.loads(row["headers_json"]),
        payload=json.loads(row["payload_json"]),
        created_at=float(row["created_at"]),
    )
