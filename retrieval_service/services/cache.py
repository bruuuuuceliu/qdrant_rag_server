"""Two-tier cache for the RAG engine.

Tier 1 — In-memory retrieval cache:
  - Per-project ``OrderedDict`` with LRU eviction.
  - 5,000 entries per project, 1-hour TTL.
  - Concurrency-safe via per-project ``asyncio.Lock``.

Tier 2 — SQLite response cache:
  - Durable on-disk cache for full LLM responses.
  - Scoped by ``project_id`` and ``user_id``.
  - 1-hour TTL, survives engine restart.
  - Stored at ``/var/lib/rag/response_cache.db``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import sqlite3
import time
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RESPONSE_CACHE_DB_PATH = Path("/var/lib/rag/response_cache.db")
DEFAULT_CACHE_TTL_SECONDS = 3600
DEFAULT_MAX_ENTRIES_PER_PROJECT = 5000


def _hash_key(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


class Tier1MemoryCache:
    """In-memory retrieval cache, one OrderedDict per project."""

    def __init__(
        self,
        *,
        max_entries_per_project: int = DEFAULT_MAX_ENTRIES_PER_PROJECT,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._max_entries = max_entries_per_project
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        self._stores: dict[str, OrderedDict[str, tuple[float, Any]]] = {}

    async def get(
        self, project_id: str, cache_key: str
    ) -> Any | None:
        async with self._lock:
            store = self._stores.get(project_id)
            if store is None:
                return None
            entry = store.get(cache_key)
            if entry is None:
                return None
            expiry, value = entry
            if expiry < time.monotonic():
                del store[cache_key]
                return None
            store.move_to_end(cache_key)
            return value

    async def set(
        self, project_id: str, cache_key: str, value: Any
    ) -> None:
        async with self._lock:
            store = self._stores.setdefault(project_id, OrderedDict())
            if cache_key in store:
                del store[cache_key]
            elif len(store) >= self._max_entries:
                store.popitem(last=False)
            expiry = time.monotonic() + self._ttl_seconds
            store[cache_key] = (expiry, value)

    async def invalidate_project(self, project_id: str) -> None:
        async with self._lock:
            self._stores.pop(project_id, None)
            logger.debug("tier1: invalidated project %s", project_id)

    async def invalidate_user(
        self, project_id: str, _user_id: str
    ) -> None:
        await self.invalidate_project(project_id)

    async def clear_expired(self) -> int:
        removed = 0
        now = time.monotonic()
        async with self._lock:
            empty_projects: list[str] = []
            for pid, store in self._stores.items():
                expired_keys = [
                    k for k, (exp, _) in store.items() if exp < now
                ]
                for k in expired_keys:
                    del store[k]
                removed += len(expired_keys)
                if not store:
                    empty_projects.append(pid)
            for pid in empty_projects:
                del self._stores[pid]
        return removed


class Tier2ResponseCache:
    """Durable SQLite cache for full LLM responses."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_RESPONSE_CACHE_DB_PATH,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self.db_path = Path(db_path)
        self._ttl_seconds = ttl_seconds

    async def initialize(self) -> None:
        self._initialize_sync()

    async def get(
        self, project_id: str, user_id: str, cache_key: str
    ) -> str | None:
        return self._get_sync(project_id, user_id, cache_key)

    async def set(
        self,
        project_id: str,
        user_id: str,
        cache_key: str,
        response: str,
    ) -> None:
        self._set_sync(project_id, user_id, cache_key, response)

    async def invalidate_project(self, project_id: str) -> None:
        self._delete_by_project_sync(project_id)
        logger.debug("tier2: invalidated project %s", project_id)

    async def invalidate_user(self, project_id: str, user_id: str) -> None:
        self._delete_by_user_sync(project_id, user_id)
        logger.debug("tier2: invalidated user %s/%s", project_id, user_id)

    async def clear_expired(self) -> int:
        return self._delete_expired_sync()

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
                CREATE TABLE IF NOT EXISTS responses (
                  project_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  cache_key TEXT NOT NULL,
                  response TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  PRIMARY KEY (project_id, user_id, cache_key)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_responses_expires
                ON responses(expires_at)
                """
            )

    def _get_sync(
        self, project_id: str, user_id: str, cache_key: str
    ) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT response, expires_at
                FROM responses
                WHERE project_id = ? AND user_id = ? AND cache_key = ?
                """,
                (project_id, user_id, cache_key),
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < time.time():
            self._delete_sync(project_id, user_id, cache_key)
            return None
        return row["response"]

    def _set_sync(
        self,
        project_id: str,
        user_id: str,
        cache_key: str,
        response: str,
    ) -> None:
        expires_at = time.time() + self._ttl_seconds
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO responses
                  (project_id, user_id, cache_key, response, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, user_id, cache_key, response, expires_at),
            )

    def _delete_sync(
        self, project_id: str, user_id: str, cache_key: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM responses
                WHERE project_id = ? AND user_id = ? AND cache_key = ?
                """,
                (project_id, user_id, cache_key),
            )

    def _delete_by_project_sync(self, project_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM responses WHERE project_id = ?",
                (project_id,),
            )

    def _delete_by_user_sync(
        self, project_id: str, user_id: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM responses WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )

    def _delete_expired_sync(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM responses WHERE expires_at < ?",
                (time.time(),),
            )
            return cursor.rowcount
