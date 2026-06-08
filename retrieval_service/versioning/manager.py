"""Embedding version manager for the RAG engine.

Handles collection lifecycle across embedding and chunker version
changes: creating new collections, atomic version swaps, grace-period
tracking, and scheduled deletion of old collections.

The version state is stored in the same SQLite config database
(``versions`` table).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from configs.project.repository import SQLiteProjectConfigRepository
from retrieval_service.core.models import BaseProjectConfig

DEFAULT_GRACE_PERIOD_SECONDS = 7 * 24 * 3600  # 7 days


@dataclass
class VersionInfo:
    version: str
    embedding_model: str
    chunker_version: str
    collection_name: str
    created_at: float
    is_active: bool


class VersionManager:
    """Manages Qdrant collection versions for embedding/chunker upgrades."""

    def __init__(
        self,
        *,
        config_repo: SQLiteProjectConfigRepository,
        grace_period_seconds: int = DEFAULT_GRACE_PERIOD_SECONDS,
    ) -> None:
        self._config_repo = config_repo
        self._grace_period = grace_period_seconds

    async def initialize(self) -> None:
        self._initialize_versions_table()

    async def create_new_version(
        self,
        project_id: str,
        new_version: str,
        *,
        embedding_model: str = "bge-base",
        chunker_version: str = "v1",
        make_active: bool = False,
    ) -> VersionInfo:
        config = await self._config_repo.get_project_config(project_id)
        collection_name = f"rag_{project_id}_{new_version}"
        now = time.time()

        self._insert_version_record(
            project_id=project_id,
            version=new_version,
            embedding_model=embedding_model,
            chunker_version=chunker_version,
            collection_name=collection_name,
            is_active=False,
            created_at=now,
        )

        if make_active:
            await self.activate_version(project_id, new_version)

        return VersionInfo(
            version=new_version,
            embedding_model=embedding_model,
            chunker_version=chunker_version,
            collection_name=collection_name,
            created_at=now,
            is_active=make_active,
        )

    async def activate_version(
        self, project_id: str, version: str
    ) -> None:
        versions = self._list_versions(project_id)
        target = next(
            (v for v in versions if v["version"] == version), None
        )
        if target is None:
            raise VersionNotFoundError(
                f"version {version!r} not found for project {project_id!r}"
            )

        for v in versions:
            self._set_active(project_id, v["version"], False)

        self._set_active(project_id, version, True)
        await self._config_repo.set_active_embedding_version(project_id, version)

    async def get_active_version(self, project_id: str) -> VersionInfo | None:
        versions = self._list_versions(project_id)
        for v in versions:
            if v["is_active"]:
                return VersionInfo(
                    version=v["version"],
                    embedding_model=v["embedding_model"],
                    chunker_version=v["chunker_version"],
                    collection_name=v["collection_name"],
                    created_at=v["created_at"],
                    is_active=True,
                )
        return None

    async def list_versions(self, project_id: str) -> list[VersionInfo]:
        return [
            VersionInfo(
                version=v["version"],
                embedding_model=v["embedding_model"],
                chunker_version=v["chunker_version"],
                collection_name=v["collection_name"],
                created_at=v["created_at"],
                is_active=v["is_active"],
            )
            for v in self._list_versions(project_id)
        ]

    async def delete_expired_versions(self, project_id: str) -> list[str]:
        now = time.time()
        deleted: list[str] = []
        versions = self._list_versions(project_id)

        for v in versions:
            if v["is_active"]:
                continue
            age = now - v["created_at"]
            if age >= self._grace_period:
                self._delete_version(project_id, v["version"])
                deleted.append(v["collection_name"])

        return deleted

    def _initialize_versions_table(self) -> None:
        self._config_repo._initialize_sync()
        with self._config_repo._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS versions (
                  project_id TEXT NOT NULL,
                  version TEXT NOT NULL,
                  embedding_model TEXT NOT NULL,
                  chunker_version TEXT NOT NULL,
                  collection_name TEXT NOT NULL,
                  is_active INTEGER NOT NULL DEFAULT 0,
                  created_at REAL NOT NULL,
                  PRIMARY KEY (project_id, version)
                )
                """
            )

    def _insert_version_record(
        self,
        *,
        project_id: str,
        version: str,
        embedding_model: str,
        chunker_version: str,
        collection_name: str,
        is_active: bool,
        created_at: float,
    ) -> None:
        with self._config_repo._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO versions
                  (project_id, version, embedding_model, chunker_version,
                   collection_name, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    version,
                    embedding_model,
                    chunker_version,
                    collection_name,
                    int(is_active),
                    created_at,
                ),
            )

    def _list_versions(self, project_id: str) -> list[dict[str, Any]]:
        with self._config_repo._connect() as connection:
            rows = connection.execute(
                """
                SELECT version, embedding_model, chunker_version,
                       collection_name, is_active, created_at
                FROM versions
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()

        return [
            {
                "version": row["version"],
                "embedding_model": row["embedding_model"],
                "chunker_version": row["chunker_version"],
                "collection_name": row["collection_name"],
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _set_active(
        self, project_id: str, version: str, is_active: bool
    ) -> None:
        with self._config_repo._connect() as connection:
            connection.execute(
                """
                UPDATE versions SET is_active = ?
                WHERE project_id = ? AND version = ?
                """,
                (int(is_active), project_id, version),
            )

    def _delete_version(self, project_id: str, version: str) -> None:
        with self._config_repo._connect() as connection:
            connection.execute(
                "DELETE FROM versions WHERE project_id = ? AND version = ?",
                (project_id, version),
            )


class VersionNotFoundError(LookupError):
    """Raised when a requested version does not exist."""
