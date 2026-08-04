"""Shared Postgres access helpers for the durable RAG stores.

Each async store owns one ``AsyncConnectionPool``, built at the wiring
composition root from its ``*_DB_URL`` DSN and opened with the service
lifetime; repos acquire a connection per call, mirroring the per-call
``sqlite3.connect`` in the SQLite implementations. Placement is the one
synchronous store and uses a short-lived sync ``Connection`` per call.
``dict_row`` maps rows onto the same ``row["col"]`` access the SQLite repos
use, so the row-to-model helpers port unchanged.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


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
