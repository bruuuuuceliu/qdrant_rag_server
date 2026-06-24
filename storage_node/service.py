"""Storage helper node service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class StorageResult:
    ok: bool
    key: str
    value: str = ""
    error: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok, "key": self.key}
        if self.value:
            payload["value"] = self.value
        if self.error:
            payload["error"] = self.error
        return payload


class FilesystemStorageService:
    """Small storage implementation owned by the storage node."""

    def __init__(self, *, root: str | Path) -> None:
        self._root = Path(root)

    async def put(self, *, key: str, value: str) -> StorageResult:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return StorageResult(ok=True, key=key)

    async def get(self, *, key: str) -> StorageResult:
        path = self._path(key)
        if not path.exists():
            return StorageResult(ok=False, key=key, error="not_found")
        return StorageResult(ok=True, key=key, value=path.read_text(encoding="utf-8"))

    async def delete(self, *, key: str) -> StorageResult:
        path = self._path(key)
        if path.exists():
            path.unlink()
        return StorageResult(ok=True, key=key)

    def _path(self, key: str) -> Path:
        clean_key = key.strip().lstrip("/")
        if not clean_key or ".." in Path(clean_key).parts:
            raise ValueError("storage key must be a relative path")
        return self._root / clean_key
