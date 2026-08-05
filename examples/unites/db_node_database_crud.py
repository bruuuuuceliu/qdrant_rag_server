"""Database-node CRUD showcase (Postgres-backed).

Setup:
1. Install dependencies: ``python -m pip install -e .``
2. Optional: set ``RAG_POSTGRES_URL`` in ``examples/unites/.env``.
3. Run: ``python -m examples.unites.db_node_database_crud``

The database node owns the logical database registry and schema-version
ledger in the shared Postgres database. The owning service keeps its own
business schema in the same Postgres database.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from db_node import DbNodeService, DbNodeSettings  # noqa: E402
from shared.postgres import pg_dsn  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"))

OWNER_SERVICE = "examples_unites"
DATABASE_NAME = "showcase_database"
SCHEMA_NAME = "showcase_items"


@dataclass(frozen=True, slots=True)
class DbNodeCrudSummary:
    target_schema: str
    created_value: str
    updated_value: str
    deleted_count: int
    health_ok: bool


async def run_db_node_crud(dsn: str) -> DbNodeCrudSummary:
    service = DbNodeService(dsn)
    await service.initialize()
    target_schema = await service.allocate_database(
        owner_service=OWNER_SERVICE,
        database_name=DATABASE_NAME,
        purpose="examples/unites db_node CRUD showcase",
        schema_version=1,
    )
    await service.record_schema_version(
        owner_service=OWNER_SERVICE,
        database_name=DATABASE_NAME,
        schema_name=SCHEMA_NAME,
        version=1,
    )

    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
        await conn.execute("DROP TABLE IF EXISTS showcase_items")
        await conn.execute(
            """
            CREATE TABLE showcase_items (
                id TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            INSERT INTO showcase_items (id, value)
            VALUES (%s, %s)
            ON CONFLICT(id) DO UPDATE SET value = EXCLUDED.value
            """,
            ("item-1", "created"),
        )
        created_row = await (
            await conn.execute(
                "SELECT value FROM showcase_items WHERE id = %s",
                ("item-1",),
            )
        ).fetchone()
        created_value = str(created_row["value"])
        await conn.execute(
            "UPDATE showcase_items SET value = %s WHERE id = %s",
            ("updated", "item-1"),
        )
        updated_row = await (
            await conn.execute(
                "SELECT value FROM showcase_items WHERE id = %s",
                ("item-1",),
            )
        ).fetchone()
        updated_value = str(updated_row["value"])
        await conn.execute("DELETE FROM showcase_items WHERE id = %s", ("item-1",))
        count_row = await (await conn.execute("SELECT COUNT(*) AS n FROM showcase_items")).fetchone()
        deleted_count = int(count_row["n"])

    health = await service.record_health_check(
        owner_service=OWNER_SERVICE,
        database_name=DATABASE_NAME,
        ok=True,
    )
    await service.close()
    return DbNodeCrudSummary(
        target_schema=target_schema,
        created_value=created_value,
        updated_value=updated_value,
        deleted_count=deleted_count,
        health_ok=health.ok,
    )


async def main() -> None:
    settings = DbNodeSettings.from_values(dict(os.environ))
    summary = await run_db_node_crud(pg_dsn(settings.db_url))

    print("Database-node CRUD complete")
    print(f"target_schema={summary.target_schema}")
    print(f"created_value={summary.created_value}")
    print(f"updated_value={summary.updated_value}")
    print(f"rows_after_delete={summary.deleted_count}")
    print(f"health_ok={summary.health_ok}")


if __name__ == "__main__":
    asyncio.run(main())
