"""SQLite database-node settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SQLiteNodeSettings:
    service_name: str = "sqlite_node"
    database_root: str = "/tmp/qdrant_rag/sqlite"

    @classmethod
    def from_values(cls, values: dict[str, str]) -> SQLiteNodeSettings:
        return cls(
            service_name=values.get("SQLITE_NODE_SERVICE_NAME", "sqlite_node"),
            database_root=values.get("SQLITE_NODE_DATABASE_ROOT", "/tmp/qdrant_rag/sqlite"),
        )

