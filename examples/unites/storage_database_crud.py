"""Storage node CRUD showcase.

Setup:
1. Install dependencies: ``python -m pip install -e .``
2. Optional: set ``STORAGE_NODE_ROOT`` in ``examples/unites/.env``.
3. Run: ``python -m examples.unites.storage_database_crud``

This showcase uses the storage node service boundary directly, matching the
same put/get/delete operations handled by the storage helper node.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from storage_node import FilesystemStorageService  # noqa: E402
from storage_node.config import StorageNodeSettings  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"))


@dataclass(frozen=True, slots=True)
class StorageCrudSummary:
    put: dict[str, Any]
    get: dict[str, Any]
    delete: dict[str, Any]
    missing: dict[str, Any]


async def run_storage_crud(storage_root: str | Path) -> StorageCrudSummary:
    storage = FilesystemStorageService(root=storage_root)
    key = "examples/unites/showcase.txt"

    put = await storage.put(key=key, value="created by storage_database_crud")
    got = await storage.get(key=key)
    deleted = await storage.delete(key=key)
    missing = await storage.get(key=key)

    return StorageCrudSummary(
        put=put.to_payload(),
        get=got.to_payload(),
        delete=deleted.to_payload(),
        missing=missing.to_payload(),
    )


async def main() -> None:
    settings = StorageNodeSettings.from_values(dict(os.environ))
    summary = await run_storage_crud(settings.storage_root)

    print("Storage node CRUD complete")
    print(f"put={summary.put}")
    print(f"get={summary.get}")
    print(f"delete={summary.delete}")
    print(f"missing_after_delete={summary.missing}")


if __name__ == "__main__":
    asyncio.run(main())
