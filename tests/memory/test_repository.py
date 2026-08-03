"""SQLite memory repository tests (B1 document-kind migration)."""

from __future__ import annotations

import sqlite3

import pytest

from memory_service.models import MemoryRecord, iso_utc_now
from memory_service.repository import SQLiteMemoryRepository

_OLD_MEMORY_RECORDS_DDL = """
CREATE TABLE memory_records (
    memory_id         TEXT PRIMARY KEY,
    session_id        TEXT,
    owner_user_id     TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('message', 'compression_summary', 'fact')),
    content           TEXT NOT NULL,
    covered_from      INTEGER,
    covered_to        INTEGER,
    created_at        TEXT NOT NULL
)
"""

# A "middle" schema: created between the document-kind widening and the B1
# review pass — has 'document' in the CHECK but lacks collection_name and
# metadata_json. initialize() must widen it in place via ALTER TABLE.
_MIDDLE_MEMORY_RECORDS_DDL = """
CREATE TABLE memory_records (
    memory_id         TEXT PRIMARY KEY,
    session_id        TEXT,
    owner_user_id     TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('message', 'compression_summary', 'fact', 'document')),
    content           TEXT NOT NULL,
    covered_from      INTEGER,
    covered_to        INTEGER,
    created_at        TEXT NOT NULL
)
"""


@pytest.mark.asyncio
async def test_fresh_sqlite_repository_accepts_document_kind(tmp_path) -> None:
    """A fresh SQLiteMemoryRepository must accept ``kind='document'`` records
    (the CREATE TABLE CHECK constraint includes 'document')."""
    repo = SQLiteMemoryRepository(tmp_path / "memory.db")
    await repo.initialize()

    record = MemoryRecord(
        memory_id="doc_1",
        owner_user_id="user_1",
        agent_id="agent_1",
        kind="document",
        content="user handbook on refunds",
        created_at=iso_utc_now(),
    )
    async with repo.transaction() as tx:
        recorded = tx.insert_memory_record(record)
    assert recorded is True

    got = await repo.get_memory_record("user_1", "doc_1")
    assert got is not None
    assert got.kind == "document"
    assert await repo.count_memory_records("user_1", "agent_1", kind="document") == 1


@pytest.mark.asyncio
async def test_initialize_migrates_legacy_memory_records_check(tmp_path) -> None:
    """``initialize()`` must rebuild a legacy ``memory_records`` table whose
    CHECK lacks 'document', preserving existing rows and widening the kind."""
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(_OLD_MEMORY_RECORDS_DDL)
    conn.execute(
        "INSERT INTO memory_records"
        " (memory_id, session_id, owner_user_id, agent_id, kind, content,"
        "  covered_from, covered_to, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "old_1",
            None,
            "user_1",
            "agent_1",
            "message",
            "hello",
            None,
            None,
            "2026-08-03T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteMemoryRepository(db_path)
    await repo.initialize()

    # legacy row survived the rebuild
    got = await repo.get_memory_record("user_1", "old_1")
    assert got is not None
    assert got.kind == "message"
    assert got.content == "hello"

    # the widened CHECK now accepts 'document'
    record = MemoryRecord(
        memory_id="doc_1",
        owner_user_id="user_1",
        agent_id="agent_1",
        kind="document",
        content="user handbook",
        created_at="2026-08-03T00:00:00Z",
    )
    async with repo.transaction() as tx:
        recorded = tx.insert_memory_record(record)
    assert recorded is True
    assert await repo.count_memory_records("user_1", "agent_1", kind="document") == 1


@pytest.mark.asyncio
async def test_initialize_migration_is_idempotent(tmp_path) -> None:
    """Running ``initialize()`` twice must not rebuild again or lose data."""
    repo = SQLiteMemoryRepository(tmp_path / "memory.db")
    await repo.initialize()

    record = MemoryRecord(
        memory_id="doc_1",
        owner_user_id="user_1",
        agent_id="agent_1",
        kind="document",
        content="user handbook",
        created_at=iso_utc_now(),
    )
    async with repo.transaction() as tx:
        tx.insert_memory_record(record)

    await repo.initialize()

    assert await repo.count_memory_records("user_1", "agent_1", kind="document") == 1
    got = await repo.get_memory_record("user_1", "doc_1")
    assert got is not None
    assert got.kind == "document"


@pytest.mark.asyncio
async def test_sqlite_persists_document_collection_and_metadata(tmp_path) -> None:
    """B1-2/B1-4: document rows persist the ingest-time collection and the
    caller-supplied metadata, both read back by the repository."""
    repo = SQLiteMemoryRepository(tmp_path / "memory.db")
    await repo.initialize()

    record = MemoryRecord(
        memory_id="doc_1",
        owner_user_id="user_1",
        agent_id="agent_1",
        kind="document",
        content="user handbook",
        collection_name="custom_docs",
        metadata={"title": "Handbook", "tags": ["finance"]},
        created_at=iso_utc_now(),
    )
    async with repo.transaction() as tx:
        recorded = tx.insert_memory_record(record)
    assert recorded is True

    got = await repo.get_memory_record("user_1", "doc_1")
    assert got is not None
    assert got.collection_name == "custom_docs"
    assert got.metadata == {"title": "Handbook", "tags": ["finance"]}

    # distinct document collections are resolved for lookup
    assert await repo.list_document_collections("user_1", "agent_1") == ("custom_docs",)


@pytest.mark.asyncio
async def test_initialize_adds_collection_and_metadata_columns_to_legacy_db(tmp_path) -> None:
    """A legacy DB with 'document' in the CHECK but no collection_name /
    metadata_json columns must be widened in place, preserving rows."""
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(_MIDDLE_MEMORY_RECORDS_DDL)
    conn.execute(
        "INSERT INTO memory_records"
        " (memory_id, session_id, owner_user_id, agent_id, kind, content,"
        "  covered_from, covered_to, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "doc_legacy",
            None,
            "user_1",
            "agent_1",
            "document",
            "legacy doc",
            None,
            None,
            "2026-08-03T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteMemoryRepository(db_path)
    await repo.initialize()

    cols = {
        row[1]
        for row in sqlite3.connect(str(db_path)).execute("PRAGMA table_info(memory_records)").fetchall()
    }
    assert "collection_name" in cols
    assert "metadata_json" in cols

    # legacy row survived with default collection/metadata
    got = await repo.get_memory_record("user_1", "doc_legacy")
    assert got is not None
    assert got.kind == "document"
    assert got.collection_name == ""
    assert got.metadata == {}
    # legacy rows without a collection resolve to nothing (lookup falls back to
    # the configured collection)
    assert await repo.list_document_collections("user_1", "agent_1") == ()
