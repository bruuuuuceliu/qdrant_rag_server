"""Postgres-backed database-node service.

Owns the logical database registry, schema-version ledger, and health-check
recorder for the durable RAG stores. ``allocate_database`` resolves a logical
database to a target schema name in the shared Postgres database (the stores no
longer allocate on-disk files).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from shared.postgres import async_pool


@dataclass(frozen=True, slots=True)
class DatabaseRecord:
    database_name: str
    owner_service: str
    purpose: str
    target_schema: str
    schema_version: int
    state: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AllocationRecord:
    allocation_id: str
    database_name: str
    owner_service: str
    requested_name: str
    resolved_schema: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SchemaVersionRecord:
    owner_service: str
    database_name: str
    schema_name: str
    version: int
    checksum: str
    applied_at: str


@dataclass(frozen=True, slots=True)
class HealthCheckRecord:
    check_id: int
    database_name: str
    owner_service: str
    ok: bool
    error: str
    checked_at: str


_DB_NODE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS db_node_databases (
        database_name TEXT PRIMARY KEY,
        owner_service TEXT NOT NULL,
        purpose TEXT NOT NULL,
        target_schema TEXT NOT NULL UNIQUE,
        schema_version INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_db_node_databases_owner
        ON db_node_databases(owner_service);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_db_node_databases_state
        ON db_node_databases(state);
    """,
    """
    CREATE TABLE IF NOT EXISTS db_node_schema_versions (
        owner_service TEXT NOT NULL,
        database_name TEXT NOT NULL,
        schema_name TEXT NOT NULL,
        version INTEGER NOT NULL,
        checksum TEXT NOT NULL DEFAULT '',
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        PRIMARY KEY (owner_service, database_name, schema_name),
        FOREIGN KEY (database_name) REFERENCES db_node_databases(database_name)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS db_node_allocations (
        allocation_id TEXT PRIMARY KEY,
        database_name TEXT NOT NULL,
        owner_service TEXT NOT NULL,
        requested_name TEXT NOT NULL,
        resolved_schema TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        FOREIGN KEY (database_name) REFERENCES db_node_databases(database_name)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_db_node_allocations_database
        ON db_node_allocations(database_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_db_node_allocations_owner
        ON db_node_allocations(owner_service);
    """,
    """
    CREATE TABLE IF NOT EXISTS db_node_health_checks (
        check_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        database_name TEXT NOT NULL,
        owner_service TEXT NOT NULL,
        ok INTEGER NOT NULL,
        error TEXT NOT NULL DEFAULT '',
        checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        FOREIGN KEY (database_name) REFERENCES db_node_databases(database_name)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_db_node_health_database_time
        ON db_node_health_checks(database_name, checked_at);
    """,
)


class DbNodeService:
    """Owns the logical database registry in the shared Postgres database."""

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self._pool = async_pool(db_url)
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        await self._pool.open()
        await self._pool.wait()
        async with self._pool.connection() as conn:
            for statement in _DB_NODE_DDL:
                await conn.execute(statement)
        self._initialized = True

    async def initialize(self) -> None:
        await self._ensure_initialized()

    async def close(self) -> None:
        await self._pool.close()

    async def allocate_database(
        self,
        *,
        owner_service: str,
        database_name: str,
        purpose: str,
        schema_version: int = 1,
    ) -> str:
        await self._ensure_initialized()
        clean_owner = _validate_identifier(owner_service, label="owner_service")
        clean_name = _validate_identifier(database_name, label="database_name")
        clean_purpose = purpose.strip()
        if not clean_purpose:
            raise ValueError("purpose is required")
        if schema_version < 1:
            raise ValueError("schema_version must be positive")
        target_schema = _schema_name(clean_name)
        async with self._pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT database_name, owner_service, target_schema"
                    "  FROM db_node_databases WHERE database_name = %s",
                    (clean_name,),
                )
            ).fetchone()
            if row is not None and row["owner_service"] != clean_owner:
                raise ValueError(
                    f"database {clean_name!r} is already owned by {row['owner_service']!r}"
                )
            if row is None:
                await conn.execute(
                    "INSERT INTO db_node_databases ("
                    " database_name, owner_service, purpose, target_schema, schema_version, state"
                    ") VALUES (%s, %s, %s, %s, %s, 'active')",
                    (clean_name, clean_owner, clean_purpose, target_schema, schema_version),
                )
            else:
                await conn.execute(
                    "UPDATE db_node_databases"
                    "   SET purpose = %s, schema_version = %s, state = 'active',"
                    "       updated_at = CURRENT_TIMESTAMP::text"
                    " WHERE database_name = %s",
                    (clean_purpose, schema_version, clean_name),
                )
            await conn.execute(
                "INSERT INTO db_node_allocations ("
                " allocation_id, database_name, owner_service, requested_name, resolved_schema"
                ") VALUES (%s, %s, %s, %s, %s)",
                (uuid4().hex, clean_name, clean_owner, database_name, target_schema),
            )
        return target_schema

    async def record_schema_version(
        self,
        *,
        owner_service: str,
        database_name: str,
        schema_name: str,
        version: int,
        checksum: str = "",
    ) -> SchemaVersionRecord:
        await self._ensure_initialized()
        clean_owner = _validate_identifier(owner_service, label="owner_service")
        clean_database = _validate_identifier(database_name, label="database_name")
        clean_schema = _validate_identifier(schema_name, label="schema_name")
        if version < 1:
            raise ValueError("version must be positive")
        async with self._pool.connection() as conn:
            await self._require_owner(conn, database_name=clean_database, owner_service=clean_owner)
            await conn.execute(
                "INSERT INTO db_node_schema_versions ("
                " owner_service, database_name, schema_name, version, checksum"
                ") VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT(owner_service, database_name, schema_name) DO UPDATE SET"
                "   version = EXCLUDED.version,"
                "   checksum = EXCLUDED.checksum,"
                "   applied_at = CURRENT_TIMESTAMP::text",
                (clean_owner, clean_database, clean_schema, version, checksum),
            )
            row = await (
                await conn.execute(
                    "SELECT owner_service, database_name, schema_name, version, checksum, applied_at"
                    "  FROM db_node_schema_versions"
                    " WHERE owner_service = %s AND database_name = %s AND schema_name = %s",
                    (clean_owner, clean_database, clean_schema),
                )
            ).fetchone()
        return _schema_version_from_row(row)

    async def record_health_check(
        self,
        *,
        database_name: str,
        owner_service: str,
        ok: bool,
        error: str = "",
    ) -> HealthCheckRecord:
        await self._ensure_initialized()
        clean_database = _validate_identifier(database_name, label="database_name")
        clean_owner = _validate_identifier(owner_service, label="owner_service")
        async with self._pool.connection() as conn:
            await self._require_owner(conn, database_name=clean_database, owner_service=clean_owner)
            inserted = await (
                await conn.execute(
                    "INSERT INTO db_node_health_checks (database_name, owner_service, ok, error)"
                    " VALUES (%s, %s, %s, %s) RETURNING check_id",
                    (clean_database, clean_owner, 1 if ok else 0, error),
                )
            ).fetchone()
            row = await (
                await conn.execute(
                    "SELECT check_id, database_name, owner_service, ok, error, checked_at"
                    "  FROM db_node_health_checks WHERE check_id = %s",
                    (inserted["check_id"],),
                )
            ).fetchone()
        return _health_check_from_row(row)

    async def list_databases(
        self,
        *,
        owner_service: str | None = None,
        state: str | None = None,
    ) -> list[DatabaseRecord]:
        await self._ensure_initialized()
        clauses: list[str] = []
        params: list[str] = []
        if owner_service is not None:
            clauses.append("owner_service = %s")
            params.append(_validate_identifier(owner_service, label="owner_service"))
        if state is not None:
            clauses.append("state = %s")
            params.append(state.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    f"""
                    SELECT database_name, owner_service, purpose, target_schema,
                           schema_version, state, created_at, updated_at
                      FROM db_node_databases
                      {where}
                     ORDER BY owner_service, database_name
                    """,
                    tuple(params),
                )
            ).fetchall()
        return [_database_from_row(row) for row in rows]

    async def list_allocations(self, database_name: str) -> list[AllocationRecord]:
        await self._ensure_initialized()
        clean_name = _validate_identifier(database_name, label="database_name")
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT allocation_id, database_name, owner_service, requested_name,
                           resolved_schema, created_at
                      FROM db_node_allocations
                     WHERE database_name = %s
                     ORDER BY created_at, allocation_id
                    """,
                    (clean_name,),
                )
            ).fetchall()
        return [_allocation_from_row(row) for row in rows]

    async def latest_health_checks(self, database_name: str) -> list[HealthCheckRecord]:
        await self._ensure_initialized()
        clean_name = _validate_identifier(database_name, label="database_name")
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT check_id, database_name, owner_service, ok, error, checked_at
                      FROM db_node_health_checks
                     WHERE database_name = %s
                     ORDER BY checked_at DESC, check_id DESC
                    """,
                    (clean_name,),
                )
            ).fetchall()
        return [_health_check_from_row(row) for row in rows]

    async def _require_owner(
        self,
        conn,
        *,
        database_name: str,
        owner_service: str,
    ) -> None:
        row = await (
            await conn.execute(
                "SELECT owner_service FROM db_node_databases WHERE database_name = %s",
                (database_name,),
            )
        ).fetchone()
        if row is None:
            raise ValueError(f"database {database_name!r} is not allocated")
        if row["owner_service"] != owner_service:
            raise ValueError(f"database {database_name!r} is owned by {row['owner_service']!r}")


def _schema_name(name: str) -> str:
    return name


def _validate_identifier(value: str, *, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{label} is required")
    if "/" in clean or "\\" in clean or ".." in clean:
        raise ValueError(f"{label} must not contain path separators")
    return clean


def _database_from_row(row) -> DatabaseRecord:
    return DatabaseRecord(
        database_name=str(row["database_name"]),
        owner_service=str(row["owner_service"]),
        purpose=str(row["purpose"]),
        target_schema=str(row["target_schema"]),
        schema_version=int(row["schema_version"]),
        state=str(row["state"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _allocation_from_row(row) -> AllocationRecord:
    return AllocationRecord(
        allocation_id=str(row["allocation_id"]),
        database_name=str(row["database_name"]),
        owner_service=str(row["owner_service"]),
        requested_name=str(row["requested_name"]),
        resolved_schema=str(row["resolved_schema"]),
        created_at=str(row["created_at"]),
    )


def _schema_version_from_row(row) -> SchemaVersionRecord:
    return SchemaVersionRecord(
        owner_service=str(row["owner_service"]),
        database_name=str(row["database_name"]),
        schema_name=str(row["schema_name"]),
        version=int(row["version"]),
        checksum=str(row["checksum"]),
        applied_at=str(row["applied_at"]),
    )


def _health_check_from_row(row) -> HealthCheckRecord:
    return HealthCheckRecord(
        check_id=int(row["check_id"]),
        database_name=str(row["database_name"]),
        owner_service=str(row["owner_service"]),
        ok=bool(row["ok"]),
        error=str(row["error"]),
        checked_at=str(row["checked_at"]),
    )
