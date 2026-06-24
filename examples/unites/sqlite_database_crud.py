"""SQLite database-node CRUD showcase.

Setup:
1. Install dependencies: ``python -m pip install -e .``
2. Optional: set ``SQLITE_NODE_DATABASE_ROOT`` in ``examples/unites/.env``.
3. Run: ``python -m examples.unites.sqlite_database_crud``

The SQLite node owns database allocation and metadata. The owning service keeps
its own business schema inside the allocated database file.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_node import SQLiteNodeService, SQLiteNodeSettings  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"))

OWNER_SERVICE = "examples_unites"
DATABASE_NAME = "showcase_database"
SCHEMA_NAME = "showcase_items"


@dataclass(frozen=True, slots=True)
class SQLiteCrudSummary:
    database_path: Path
    created_value: str
    updated_value: str
    deleted_count: int
    health_ok: bool


async def run_sqlite_crud(database_root: str | Path) -> SQLiteCrudSummary:
    service = SQLiteNodeService(database_root=database_root)
    database_path = await service.allocate_database(
        owner_service=OWNER_SERVICE,
        database_name=DATABASE_NAME,
        purpose="examples/unites SQLite CRUD showcase",
        schema_version=1,
    )
    await service.record_schema_version(
        owner_service=OWNER_SERVICE,
        database_name=DATABASE_NAME,
        schema_name=SCHEMA_NAME,
        version=1,
    )

    with sqlite3.connect(database_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS showcase_items (
                id TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO showcase_items (id, value)
            VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET value = excluded.value
            """,
            ("item-1", "created"),
        )
        created_value = str(
            conn.execute(
                "SELECT value FROM showcase_items WHERE id = ?",
                ("item-1",),
            ).fetchone()[0]
        )
        conn.execute(
            "UPDATE showcase_items SET value = ? WHERE id = ?",
            ("updated", "item-1"),
        )
        updated_value = str(
            conn.execute(
                "SELECT value FROM showcase_items WHERE id = ?",
                ("item-1",),
            ).fetchone()[0]
        )
        conn.execute("DELETE FROM showcase_items WHERE id = ?", ("item-1",))
        deleted_count = int(
            conn.execute("SELECT COUNT(*) FROM showcase_items").fetchone()[0]
        )

    health = await service.record_health_check(
        owner_service=OWNER_SERVICE,
        database_name=DATABASE_NAME,
        ok=database_path.exists(),
    )
    return SQLiteCrudSummary(
        database_path=database_path,
        created_value=created_value,
        updated_value=updated_value,
        deleted_count=deleted_count,
        health_ok=health.ok,
    )


async def main() -> None:
    settings = SQLiteNodeSettings.from_values(dict(os.environ))
    summary = await run_sqlite_crud(settings.database_root)

    print("SQLite database-node CRUD complete")
    print(f"database_path={summary.database_path}")
    print(f"created_value={summary.created_value}")
    print(f"updated_value={summary.updated_value}")
    print(f"rows_after_delete={summary.deleted_count}")
    print(f"health_ok={summary.health_ok}")


if __name__ == "__main__":
    asyncio.run(main())
