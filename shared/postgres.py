"""Shared Postgres access helpers for the durable RAG stores.

Each async store owns one ``AsyncConnectionPool``, built at the wiring
composition root from its ``*_DB_URL`` DSN and opened with the service
lifetime; repos acquire a connection per call. Placement is the one
synchronous store and uses a short-lived sync ``Connection`` per call.
``dict_row`` maps rows onto ``row["col"]`` access, so the row-to-model helpers
read consistently across the async and sync seams.
"""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

#: Shared Postgres endpoint for the durable RAG stores. Overridable via the
#: ``RAG_POSTGRES_URL`` env var; individual stores may still pin their own DSN
#: through their ``*_DB_URL`` setting, which wins over this default.
DEFAULT_PG_DSN = "postgresql://rag:rag@localhost:5432/rag"


def pg_dsn(candidate: str | None = None) -> str:
    """Resolve the Postgres DSN: an explicit candidate wins, else ``RAG_POSTGRES_URL``, else the default."""
    return candidate or os.environ.get("RAG_POSTGRES_URL") or DEFAULT_PG_DSN


def async_pool(
    dsn: str,
    *,
    min_size: int = 1,
    max_size: int = 5,
) -> AsyncConnectionPool:
    """Build a closed async pool for one store; open + wait at startup."""
    return AsyncConnectionPool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={"row_factory": dict_row},
    )


def connect(dsn: str) -> psycopg.Connection:
    """Open a short-lived sync connection (placement store only)."""
    return psycopg.connect(dsn, row_factory=dict_row)
