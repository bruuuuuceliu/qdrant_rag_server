"""Pytest import path setup for service-folder tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import pytest

from shared.postgres import DEFAULT_PG_DSN

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """Postgres DSN for the always-on durable-store tests.

    Reads ``RAG_POSTGRES_URL`` (else the shared default); skips the session
    when no Postgres is reachable so a bare laptop without Postgres stays
    green while CI always runs the Postgres tests.
    """
    dsn = os.environ.get("RAG_POSTGRES_URL") or DEFAULT_PG_DSN
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres unavailable at {dsn}: {exc}")
    return dsn

