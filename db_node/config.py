"""Database-node settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DbNodeSettings:
    service_name: str = "db_node"
    db_url: str | None = None

    @classmethod
    def from_values(cls, values: dict[str, str]) -> DbNodeSettings:
        return cls(
            service_name=values.get("DB_NODE_SERVICE_NAME", "db_node"),
            db_url=values.get("DB_NODE_DB_URL") or values.get("RAG_POSTGRES_URL") or None,
        )
