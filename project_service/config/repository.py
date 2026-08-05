"""Project configuration repositories (Postgres-backed durable store)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from project_service.schemas import ProjectConfig
from shared.postgres import async_pool


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
    def from_base_config(cls, config: ProjectConfig) -> ProjectConfigRecord:
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

    def to_base_config(self) -> ProjectConfig:
        return ProjectConfig(
            project_id=self.project_id,
            project_type=self.project_type,
            active_embedding_version=self.active_embedding_version,
            embedding_model=self.embedding_model,
            reranker_model=self.reranker_model,
            chunker_config=dict(self.chunker_config),
            retrieval_config=dict(self.retrieval_config),
            cache_config=dict(self.cache_config),
        )


_PROJECT_POSTGRES_DDL = (
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
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_projects_project_type
    ON projects(project_type)
    """,
)

_UPSERT_PROJECT_SQL = """
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
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT(project_id) DO UPDATE SET
  project_type = EXCLUDED.project_type,
  active_embedding_version = EXCLUDED.active_embedding_version,
  embedding_model = EXCLUDED.embedding_model,
  reranker_model = EXCLUDED.reranker_model,
  chunker_config_json = EXCLUDED.chunker_config_json,
  retrieval_config_json = EXCLUDED.retrieval_config_json,
  cache_config_json = EXCLUDED.cache_config_json,
  updated_at = CURRENT_TIMESTAMP::text
"""

_SELECT_PROJECT_SQL = """
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
WHERE project_id = %s
"""



class PostgresProjectConfigRepository:
    """Async project config repository backed by Postgres.

    Runs directly on the async pool; no thread-pool hop is needed.
    """

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self._pool = async_pool(db_url)

    async def initialize(self) -> None:
        await self._pool.open()
        await self._pool.wait()
        async with self._pool.connection() as conn:
            for statement in _PROJECT_POSTGRES_DDL:
                await conn.execute(statement)

    async def close(self) -> None:
        await self._pool.close()

    async def upsert_project(self, config: ProjectConfig) -> None:
        record = ProjectConfigRecord.from_base_config(config)
        async with self._pool.connection() as conn:
            await conn.execute(
                _UPSERT_PROJECT_SQL,
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

    async def get_project_config(self, project_id: str) -> ProjectConfig:
        record = await self._get_project_record(project_id)
        return record.to_base_config()

    async def get_project_type(self, project_id: str) -> str:
        config = await self.get_project_config(project_id)
        return config.project_type

    async def set_active_embedding_version(
        self, project_id: str, active_embedding_version: str
    ) -> None:
        if not active_embedding_version or not active_embedding_version.strip():
            raise ValueError("active_embedding_version is required")
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "UPDATE projects SET active_embedding_version = %s,"
                " updated_at = CURRENT_TIMESTAMP::text WHERE project_id = %s",
                (active_embedding_version, project_id),
            )
            if cursor.rowcount == 0:
                raise ProjectConfigNotFoundError(
                    f"project config not found for project_id={project_id!r}"
                )

    async def _get_project_record(self, project_id: str) -> ProjectConfigRecord:
        if not project_id or not project_id.strip():
            raise ValueError("project_id is required")
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(_SELECT_PROJECT_SQL, (project_id,))
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


def _dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load_json(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("stored config JSON must be an object")
    return loaded
