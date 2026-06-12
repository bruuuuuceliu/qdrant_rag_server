"""Local filesystem object storage for development."""

from __future__ import annotations

import logging
from pathlib import Path

from retrieval_service.storage.base import ObjectStorage, ObjectStorageError

logger = logging.getLogger(__name__)


class FilesystemObjectStorage(ObjectStorage):
    """Local filesystem storage for development."""

    def __init__(self, base_path: str | Path) -> None:
        self._base_path = Path(base_path)

    async def put(self, key: str, content: bytes, content_type: str = "") -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        logger.debug("fs storage: wrote %s (%d bytes)", key, len(content))

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise ObjectStorageError(f"object not found: {key!r}")
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        path.unlink(missing_ok=True)

    async def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def _resolve(self, key: str) -> Path:
        safe_key = key.replace("..", "").lstrip("/")
        return self._base_path / safe_key
