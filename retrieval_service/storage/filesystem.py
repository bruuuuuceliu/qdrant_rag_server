"""Local filesystem object storage for development.

When an AsyncExecutor is injected, blocking I/O runs on its thread pool.
Without one (tests), calls run synchronously on the event loop thread.
"""

from __future__ import annotations

import logging
from pathlib import Path

from retrieval_service.storage.base import ObjectStorage, ObjectStorageError
from shared.executor import AsyncExecutor

logger = logging.getLogger(__name__)


class FilesystemObjectStorage(ObjectStorage):
    """Local filesystem storage for development."""

    def __init__(
        self,
        base_path: str | Path,
        *,
        executor: AsyncExecutor | None = None,
    ) -> None:
        self._base_path = Path(base_path)
        self._executor = executor

    async def put(self, key: str, content: bytes, content_type: str = "") -> None:
        if self._executor is not None:
            await self._executor.run(self._put_sync, key, content)
        else:
            self._put_sync(key, content)
        logger.debug("fs storage: wrote %s (%d bytes)", key, len(content))

    async def get(self, key: str) -> bytes:
        if self._executor is not None:
            return await self._executor.run(self._get_sync, key)
        return self._get_sync(key)

    async def delete(self, key: str) -> None:
        if self._executor is not None:
            await self._executor.run(self._delete_sync, key)
        else:
            self._delete_sync(key)

    async def exists(self, key: str) -> bool:
        if self._executor is not None:
            return await self._executor.run(self._exists_sync, key)
        return self._exists_sync(key)

    def _put_sync(self, key: str, content: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _get_sync(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise ObjectStorageError(f"object not found: {key!r}")
        return path.read_bytes()

    def _delete_sync(self, key: str) -> None:
        path = self._resolve(key)
        path.unlink(missing_ok=True)

    def _exists_sync(self, key: str) -> bool:
        return self._resolve(key).exists()

    def _resolve(self, key: str) -> Path:
        safe_key = key.replace("..", "").lstrip("/")
        return self._base_path / safe_key
