"""Storage node service tests."""

from __future__ import annotations

import pytest

from storage_node import FilesystemStorageService


@pytest.mark.asyncio
async def test_filesystem_storage_service_put_get_delete(tmp_path) -> None:
    storage = FilesystemStorageService(root=tmp_path)

    put = await storage.put(key="docs/a.txt", value="hello")
    got = await storage.get(key="docs/a.txt")
    deleted = await storage.delete(key="docs/a.txt")
    missing = await storage.get(key="docs/a.txt")

    assert put.ok is True
    assert got.to_payload() == {"ok": True, "key": "docs/a.txt", "value": "hello"}
    assert deleted.ok is True
    assert missing.to_payload() == {"ok": False, "key": "docs/a.txt", "error": "not_found"}


@pytest.mark.asyncio
async def test_filesystem_storage_rejects_path_traversal(tmp_path) -> None:
    storage = FilesystemStorageService(root=tmp_path)

    with pytest.raises(ValueError, match="relative"):
        await storage.put(key="../secret", value="bad")
