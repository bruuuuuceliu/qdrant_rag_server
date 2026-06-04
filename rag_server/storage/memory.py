"""In-memory object storage for testing."""

from __future__ import annotations

from rag_server.storage.base import ObjectStorage, ObjectStorageError


class MemoryObjectStorage(ObjectStorage):
    """In-memory storage for testing."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes, content_type: str = "") -> None:
        self._store[key] = content

    async def get(self, key: str) -> bytes:
        try:
            return self._store[key]
        except KeyError as exc:
            raise ObjectStorageError(f"object not found: {key!r}") from exc

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._store
