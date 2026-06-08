"""SQLite-backed project configuration repository."""

from __future__ import annotations

import json
import contextlib
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from retrieval_service.core.schemas import BaseProjectConfig


DEFAULT_CONFIG_DB_PATH = Path("/var/lib/rag/config.db")


class ProjectConfigNotFoundError(LookupError):
    """Raised when a project config does not exist."""


@dataclass(frozen=True, slots=True)
class ProjectConfigRecord:
    """Storage record for a project config."""

    project_id: str
    project_type: str
    active_embedding_version: str
    embedding_model: str
    reranker_model: str
    chunker_config: dict[str, Any]
    retrieval_config: dict[str, Any]
    cache_config: dict[str, Any]

    @classmethod
    def from_base_config(cls, config: BaseProjectConfig) -> ProjectConfigRecord:
        return cls(
            project_id=config.project_id,
            project_type=config.project_type,
            active_embedding_version=config.active_embedding_version,
            embedding_model=config.embedding_model,
            reranker_model=config.reranker_model,
            chunker_config=dict(config.chunker_config),
            retrieval_config=dict(config.retrieval_config),
            cache_config=dict(config.cache_config),
        )

    def to_base_config(self) -> BaseProjectConfig:
        return BaseProjectConfig(
            project_id=self.project_id,
            project_type=self.project_type,
            active_embedding_version=self.active_embedding_version,
            embedding_model=self.embedding_model,
            reranker_model=self.reranker_model,
            chunker_config=dict(self.chunker_config),
            retrieval_config=dict(self.retrieval_config),
            cache_config=dict(self.cache_config),
        )


class SQLiteProjectConfigRepository:
    """Async project config repository backed by SQLite."""

    def __init__(self, db_path: str | Path = DEFAULT_CONFIG_DB_PATH) -> None:
        self.db_path = Path(db_path)

    async def initialize(self) -> None:
        self._initialize_sync()

    async def upsert_project(self, config: BaseProjectConfig) -> None:
        record = ProjectConfigRecord.from_base_config(config)
        self._upsert_project_sync(record)

    async def get_project_config(self, project_id: str) -> BaseProjectConfig:
        record = self._get_project_record_sync(project_id)
        return record.to_base_config()

    async def get_project_type(self, project_id: str) -> str:
        config = await self.get_project_config(project_id)
        return config.project_type

    async def set_active_embedding_version(
        self, project_id: str, active_embedding_version: str
    ) -> None:
        if not active_embedding_version or not active_embedding_version.strip():
            raise ValueError("active_embedding_version is required")
        self._set_active_embedding_version_sync(project_id, active_embedding_version)

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                  project_id TEXT PRIMARY KEY,
                  project_type TEXT NOT NULL,
                  active_embedding_version TEXT NOT NULL,
                  embedding_model TEXT NOT NULL,
                  reranker_model TEXT NOT NULL,
                  chunker_config_json TEXT NOT NULL,
                  retrieval_config_json TEXT NOT NULL,
                  cache_config_json TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_projects_project_type
                ON projects(project_type)
                """
            )

    def _upsert_project_sync(self, record: ProjectConfigRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                  project_id,
                  project_type,
                  active_embedding_version,
                  embedding_model,
                  reranker_model,
                  chunker_config_json,
                  retrieval_config_json,
                  cache_config_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                  project_type = excluded.project_type,
                  active_embedding_version = excluded.active_embedding_version,
                  embedding_model = excluded.embedding_model,
                  reranker_model = excluded.reranker_model,
                  chunker_config_json = excluded.chunker_config_json,
                  retrieval_config_json = excluded.retrieval_config_json,
                  cache_config_json = excluded.cache_config_json,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.project_id,
                    record.project_type,
                    record.active_embedding_version,
                    record.embedding_model,
                    record.reranker_model,
                    _dump_json(record.chunker_config),
                    _dump_json(record.retrieval_config),
                    _dump_json(record.cache_config),
                ),
            )

    def _get_project_record_sync(self, project_id: str) -> ProjectConfigRecord:
        if not project_id or not project_id.strip():
            raise ValueError("project_id is required")

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                  project_id,
                  project_type,
                  active_embedding_version,
                  embedding_model,
                  reranker_model,
                  chunker_config_json,
                  retrieval_config_json,
                  cache_config_json
                FROM projects
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()

        if row is None:
            raise ProjectConfigNotFoundError(
                f"project config not found for project_id={project_id!r}"
            )

        return ProjectConfigRecord(
            project_id=row["project_id"],
            project_type=row["project_type"],
            active_embedding_version=row["active_embedding_version"],
            embedding_model=row["embedding_model"],
            reranker_model=row["reranker_model"],
            chunker_config=_load_json(row["chunker_config_json"]),
            retrieval_config=_load_json(row["retrieval_config_json"]),
            cache_config=_load_json(row["cache_config_json"]),
        )

    def _set_active_embedding_version_sync(
        self, project_id: str, active_embedding_version: str
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE projects
                SET active_embedding_version = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE project_id = ?
                """,
                (active_embedding_version, project_id),
            )
            if cursor.rowcount == 0:
                raise ProjectConfigNotFoundError(
                    f"project config not found for project_id={project_id!r}"
                )


def _dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load_json(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("stored config JSON must be an object")
    return loaded
