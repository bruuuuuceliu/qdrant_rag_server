"""Async concurrency limiter — caps active requests per project and per user."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from project_service.gateway.errors import ConcurrencyLimitExceededError


class AsyncConcurrencyLimiter:
    """Tracks active requests by project and user without blocking the event loop."""

    def __init__(self, *, max_per_project: int, max_per_user: int) -> None:
        if max_per_project <= 0:
            raise ValueError("max_per_project must be positive")
        if max_per_user <= 0:
            raise ValueError("max_per_user must be positive")

        self.max_per_project = max_per_project
        self.max_per_user = max_per_user
        self._lock = asyncio.Lock()
        self._project_counts: dict[str, int] = {}
        self._user_counts: dict[tuple[str, str], int] = {}

    @asynccontextmanager
    async def limit(self, project_id: str, user_id: str) -> AsyncIterator[None]:
        await self._acquire(project_id, user_id)
        try:
            yield
        finally:
            await self._release(project_id, user_id)

    async def _acquire(self, project_id: str, user_id: str) -> None:
        async with self._lock:
            project_count = self._project_counts.get(project_id, 0)
            user_key = (project_id, user_id)
            user_count = self._user_counts.get(user_key, 0)

            if project_count >= self.max_per_project:
                raise ConcurrencyLimitExceededError(
                    f"project concurrency limit exceeded for project_id={project_id!r}"
                )
            if user_count >= self.max_per_user:
                raise ConcurrencyLimitExceededError(
                    "user concurrency limit exceeded for "
                    f"project_id={project_id!r}, user_id={user_id!r}"
                )

            self._project_counts[project_id] = project_count + 1
            self._user_counts[user_key] = user_count + 1

    async def _release(self, project_id: str, user_id: str) -> None:
        async with self._lock:
            user_key = (project_id, user_id)
            self._decrement(self._project_counts, project_id)
            self._decrement(self._user_counts, user_key)

    @staticmethod
    def _decrement(counts: dict[Any, int], key: Any) -> None:
        next_value = counts[key] - 1
        if next_value <= 0:
            del counts[key]
        else:
            counts[key] = next_value
