"""Workflow log repositories."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

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

    async def append(self, entry: WorkflowLogEntry) -> None:
        self._entries.append(entry)

    async def list_by_job(self, job_id: str) -> list[WorkflowLogEntry]:
        return [entry for entry in self._entries if entry.job_id == job_id]

    async def list_all(self) -> list[WorkflowLogEntry]:
        return list(self._entries)


class SQLiteWorkflowLogRepository:
    """SQLite-backed workflow log repository."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    async def initialize(self) -> None:
        self._initialize_sync()

    async def append(self, entry: WorkflowLogEntry) -> None:
        self._append_sync(entry)

    async def list_by_job(self, job_id: str) -> list[WorkflowLogEntry]:
        return self._list_sync("WHERE job_id = ?", (job_id,))

    async def list_all(self) -> list[WorkflowLogEntry]:
        return self._list_sync("", ())

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_log_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_log_job
                    ON workflow_log_entries(job_id);
                CREATE INDEX IF NOT EXISTS idx_workflow_log_project_user
                    ON workflow_log_entries(project_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_workflow_log_event
                    ON workflow_log_entries(event);
                """
            )

    def _append_sync(self, entry: WorkflowLogEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_log_entries (
                    event, job_id, status, project_id, user_id, kb_id, doc_id,
                    data_type, content_hash, raw_storage_key, error, topic,
                    message_key, headers_json, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
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

    def _list_sync(
        self,
        where: str,
        params: tuple[object, ...],
    ) -> list[WorkflowLogEntry]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT event, job_id, status, project_id, user_id, kb_id, doc_id,
                       data_type, content_hash, raw_storage_key, error, topic,
                       message_key, headers_json, payload_json, created_at
                  FROM workflow_log_entries
                  {where}
                 ORDER BY id ASC
                """,
                params,
            ).fetchall()
        return [_entry_from_row(row) for row in rows]


def _entry_from_row(row: sqlite3.Row) -> WorkflowLogEntry:
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
