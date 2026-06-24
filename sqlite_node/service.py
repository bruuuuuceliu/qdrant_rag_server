"""SQLite database-node service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class SQLiteDatabaseRecord:
    database_name: str
    owner_service: str
    purpose: str
    relative_path: str
    schema_version: int
    state: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SQLiteAllocationRecord:
    allocation_id: str
    database_name: str
    owner_service: str
    requested_name: str
    resolved_path: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SQLiteSchemaVersionRecord:
    owner_service: str
    database_name: str
    schema_name: str
    version: int
    checksum: str
    applied_at: str


@dataclass(frozen=True, slots=True)
class SQLiteHealthCheckRecord:
    check_id: int
    database_name: str
    owner_service: str
    ok: bool
    error: str
    checked_at: str


class SQLiteNodeService:
    """Owns database path allocation for small SQLite databases."""

    def __init__(self, *, database_root: str | Path) -> None:
        self._database_root = Path(database_root)

    @property
    def database_root(self) -> Path:
        return self._database_root

    @property
    def metadata_db_path(self) -> Path:
        return self._database_root / "_sqlite_node.db"

    def database_path(self, name: str) -> Path:
        clean_name = _validate_file_name(name, label="database name")
        if not clean_name.endswith(".db"):
            clean_name = f"{clean_name}.db"
        return self._database_root / clean_name

    async def initialize(self) -> None:
        self._database_root.mkdir(parents=True, exist_ok=True)
        with self._connect_metadata() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS db_node_databases (
                    database_name TEXT PRIMARY KEY,
                    owner_service TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    state TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_db_node_databases_owner
                    ON db_node_databases(owner_service);
                CREATE INDEX IF NOT EXISTS idx_db_node_databases_state
                    ON db_node_databases(state);

                CREATE TABLE IF NOT EXISTS db_node_schema_versions (
                    owner_service TEXT NOT NULL,
                    database_name TEXT NOT NULL,
                    schema_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    checksum TEXT NOT NULL DEFAULT '',
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (owner_service, database_name, schema_name),
                    FOREIGN KEY (database_name) REFERENCES db_node_databases(database_name)
                );

                CREATE TABLE IF NOT EXISTS db_node_allocations (
                    allocation_id TEXT PRIMARY KEY,
                    database_name TEXT NOT NULL,
                    owner_service TEXT NOT NULL,
                    requested_name TEXT NOT NULL,
                    resolved_path TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (database_name) REFERENCES db_node_databases(database_name)
                );
                CREATE INDEX IF NOT EXISTS idx_db_node_allocations_database
                    ON db_node_allocations(database_name);
                CREATE INDEX IF NOT EXISTS idx_db_node_allocations_owner
                    ON db_node_allocations(owner_service);

                CREATE TABLE IF NOT EXISTS db_node_health_checks (
                    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    database_name TEXT NOT NULL,
                    owner_service TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (database_name) REFERENCES db_node_databases(database_name)
                );
                CREATE INDEX IF NOT EXISTS idx_db_node_health_database_time
                    ON db_node_health_checks(database_name, checked_at);
                """
            )

    async def allocate_database(
        self,
        *,
        owner_service: str,
        database_name: str,
        purpose: str,
        schema_version: int = 1,
    ) -> Path:
        await self.initialize()
        clean_owner = _validate_identifier(owner_service, label="owner_service")
        clean_name = _validate_file_name(database_name, label="database_name")
        clean_purpose = purpose.strip()
        if not clean_purpose:
            raise ValueError("purpose is required")
        if schema_version < 1:
            raise ValueError("schema_version must be positive")
        relative_path = _database_file_name(clean_name)
        resolved = self._database_root / relative_path
        with self._connect_metadata() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT database_name, owner_service, relative_path
                  FROM db_node_databases
                 WHERE database_name = ?
                """,
                (clean_name,),
            ).fetchone()
            if row is not None and row["owner_service"] != clean_owner:
                raise ValueError(
                    f"database {clean_name!r} is already owned by {row['owner_service']!r}"
                )
            if row is None:
                conn.execute(
                    """
                    INSERT INTO db_node_databases (
                        database_name, owner_service, purpose, relative_path,
                        schema_version, state
                    )
                    VALUES (?, ?, ?, ?, ?, 'active')
                    """,
                    (clean_name, clean_owner, clean_purpose, relative_path, schema_version),
                )
            else:
                conn.execute(
                    """
                    UPDATE db_node_databases
                       SET purpose = ?,
                           schema_version = ?,
                           state = 'active',
                           updated_at = CURRENT_TIMESTAMP
                     WHERE database_name = ?
                    """,
                    (clean_purpose, schema_version, clean_name),
                )
            conn.execute(
                """
                INSERT INTO db_node_allocations (
                    allocation_id, database_name, owner_service, requested_name, resolved_path
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (uuid4().hex, clean_name, clean_owner, database_name, str(resolved)),
            )
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    async def record_schema_version(
        self,
        *,
        owner_service: str,
        database_name: str,
        schema_name: str,
        version: int,
        checksum: str = "",
    ) -> SQLiteSchemaVersionRecord:
        clean_owner = _validate_identifier(owner_service, label="owner_service")
        clean_database = _validate_file_name(database_name, label="database_name")
        clean_schema = _validate_identifier(schema_name, label="schema_name")
        if version < 1:
            raise ValueError("version must be positive")
        with self._connect_metadata() as conn:
            conn.row_factory = sqlite3.Row
            self._require_owner(conn, database_name=clean_database, owner_service=clean_owner)
            conn.execute(
                """
                INSERT INTO db_node_schema_versions (
                    owner_service, database_name, schema_name, version, checksum
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_service, database_name, schema_name) DO UPDATE SET
                    version = excluded.version,
                    checksum = excluded.checksum,
                    applied_at = CURRENT_TIMESTAMP
                """,
                (clean_owner, clean_database, clean_schema, version, checksum),
            )
            row = conn.execute(
                """
                SELECT owner_service, database_name, schema_name, version, checksum, applied_at
                  FROM db_node_schema_versions
                 WHERE owner_service = ? AND database_name = ? AND schema_name = ?
                """,
                (clean_owner, clean_database, clean_schema),
            ).fetchone()
        return _schema_version_from_row(row)

    async def record_health_check(
        self,
        *,
        database_name: str,
        owner_service: str,
        ok: bool,
        error: str = "",
    ) -> SQLiteHealthCheckRecord:
        clean_database = _validate_file_name(database_name, label="database_name")
        clean_owner = _validate_identifier(owner_service, label="owner_service")
        with self._connect_metadata() as conn:
            conn.row_factory = sqlite3.Row
            self._require_owner(conn, database_name=clean_database, owner_service=clean_owner)
            cursor = conn.execute(
                """
                INSERT INTO db_node_health_checks (database_name, owner_service, ok, error)
                VALUES (?, ?, ?, ?)
                """,
                (clean_database, clean_owner, 1 if ok else 0, error),
            )
            row = conn.execute(
                """
                SELECT check_id, database_name, owner_service, ok, error, checked_at
                  FROM db_node_health_checks
                 WHERE check_id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return _health_check_from_row(row)

    async def list_databases(
        self,
        *,
        owner_service: str | None = None,
        state: str | None = None,
    ) -> list[SQLiteDatabaseRecord]:
        clauses: list[str] = []
        params: list[str] = []
        if owner_service is not None:
            clauses.append("owner_service = ?")
            params.append(_validate_identifier(owner_service, label="owner_service"))
        if state is not None:
            clauses.append("state = ?")
            params.append(state.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect_metadata() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT database_name, owner_service, purpose, relative_path,
                       schema_version, state, created_at, updated_at
                  FROM db_node_databases
                  {where}
                 ORDER BY owner_service, database_name
                """,
                tuple(params),
            ).fetchall()
        return [_database_from_row(row) for row in rows]

    async def list_allocations(self, database_name: str) -> list[SQLiteAllocationRecord]:
        clean_name = _validate_file_name(database_name, label="database_name")
        with self._connect_metadata() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT allocation_id, database_name, owner_service, requested_name,
                       resolved_path, created_at
                  FROM db_node_allocations
                 WHERE database_name = ?
                 ORDER BY created_at, allocation_id
                """,
                (clean_name,),
            ).fetchall()
        return [_allocation_from_row(row) for row in rows]

    async def latest_health_checks(self, database_name: str) -> list[SQLiteHealthCheckRecord]:
        clean_name = _validate_file_name(database_name, label="database_name")
        with self._connect_metadata() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT check_id, database_name, owner_service, ok, error, checked_at
                  FROM db_node_health_checks
                 WHERE database_name = ?
                 ORDER BY checked_at DESC, check_id DESC
                """,
                (clean_name,),
            ).fetchall()
        return [_health_check_from_row(row) for row in rows]

    def _connect_metadata(self) -> sqlite3.Connection:
        self._database_root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.metadata_db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _require_owner(
        self,
        conn: sqlite3.Connection,
        *,
        database_name: str,
        owner_service: str,
    ) -> None:
        row = conn.execute(
            """
            SELECT owner_service
              FROM db_node_databases
             WHERE database_name = ?
            """,
            (database_name,),
        ).fetchone()
        if row is None:
            raise ValueError(f"database {database_name!r} is not allocated")
        if row["owner_service"] != owner_service:
            raise ValueError(f"database {database_name!r} is owned by {row['owner_service']!r}")


def _database_file_name(name: str) -> str:
    return name if name.endswith(".db") else f"{name}.db"


def _validate_file_name(value: str, *, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{label} is required")
    if Path(clean).is_absolute() or "/" in clean or "\\" in clean or ".." in clean:
        raise ValueError(f"{label} must be a file name")
    return clean[:-3] if clean.endswith(".db") else clean


def _validate_identifier(value: str, *, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{label} is required")
    if "/" in clean or "\\" in clean or ".." in clean:
        raise ValueError(f"{label} must not contain path separators")
    return clean


def _database_from_row(row: sqlite3.Row) -> SQLiteDatabaseRecord:
    return SQLiteDatabaseRecord(
        database_name=str(row["database_name"]),
        owner_service=str(row["owner_service"]),
        purpose=str(row["purpose"]),
        relative_path=str(row["relative_path"]),
        schema_version=int(row["schema_version"]),
        state=str(row["state"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _allocation_from_row(row: sqlite3.Row) -> SQLiteAllocationRecord:
    return SQLiteAllocationRecord(
        allocation_id=str(row["allocation_id"]),
        database_name=str(row["database_name"]),
        owner_service=str(row["owner_service"]),
        requested_name=str(row["requested_name"]),
        resolved_path=str(row["resolved_path"]),
        created_at=str(row["created_at"]),
    )


def _schema_version_from_row(row: sqlite3.Row) -> SQLiteSchemaVersionRecord:
    return SQLiteSchemaVersionRecord(
        owner_service=str(row["owner_service"]),
        database_name=str(row["database_name"]),
        schema_name=str(row["schema_name"]),
        version=int(row["version"]),
        checksum=str(row["checksum"]),
        applied_at=str(row["applied_at"]),
    )


def _health_check_from_row(row: sqlite3.Row) -> SQLiteHealthCheckRecord:
    return SQLiteHealthCheckRecord(
        check_id=int(row["check_id"]),
        database_name=str(row["database_name"]),
        owner_service=str(row["owner_service"]),
        ok=bool(row["ok"]),
        error=str(row["error"]),
        checked_at=str(row["checked_at"]),
    )
