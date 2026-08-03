"""Startup re-drive seam tests (§9 Index durability)."""

from __future__ import annotations

import pytest

from memory_service.models import MemoryRecord, iso_utc_now
from memory_service.reconciliation import reconcile_pending_index
from memory_service.repository import MemoryInMemoryRepository, SQLiteMemoryRepository


class _RecordingIndexer:
    """Indexer that records batches and can be told to fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.batches: list[list[MemoryRecord]] = []
        self.collections: list[str] = []

    async def index(self, records: list[MemoryRecord], *, collection_name: str = "") -> None:
        if self.fail:
            raise RuntimeError("indexer unavailable")
        self.batches.append(list(records))
        self.collections.append(collection_name)


def _record(memory_id: str, *, collection_name: str = "", kind: str = "message") -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        owner_user_id="user_1",
        agent_id="agent_1",
        kind=kind,
        content="hello",
        collection_name=collection_name,
        created_at=iso_utc_now(),
    )


@pytest.mark.asyncio
async def test_reconcile_skips_when_nothing_pending() -> None:
    repository = MemoryInMemoryRepository()
    indexer = _RecordingIndexer()

    count = await reconcile_pending_index(repository=repository, indexer=indexer)

    assert count == 0
    assert indexer.batches == []


@pytest.mark.asyncio
async def test_reconcile_requeues_and_marks_pending_records(tmp_path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "memory.db")
    await repository.initialize()
    for memory_id in ("mem_1", "mem_2"):
        async with repository.transaction() as tx:
            tx.insert_memory_record(_record(memory_id))

    indexer = _RecordingIndexer()
    count = await reconcile_pending_index(repository=repository, indexer=indexer)

    assert count == 2
    assert len(indexer.batches) == 1
    assert {r.memory_id for r in indexer.batches[0]} == {"mem_1", "mem_2"}
    assert await repository.list_memory_records_pending_index() == []


@pytest.mark.asyncio
async def test_reconcile_groups_documents_into_their_collection() -> None:
    repository = MemoryInMemoryRepository()
    async with repository.transaction() as tx:
        tx.insert_memory_record(_record("mem_1"))
        tx.insert_memory_record(_record("doc_1", collection_name="agent_documents", kind="document"))

    indexer = _RecordingIndexer()
    count = await reconcile_pending_index(repository=repository, indexer=indexer)

    assert count == 2
    by_collection = dict(zip(indexer.collections, indexer.batches))
    assert {r.memory_id for r in by_collection[""]} == {"mem_1"}
    assert {r.memory_id for r in by_collection["agent_documents"]} == {"doc_1"}
    assert await repository.list_memory_records_pending_index() == []


@pytest.mark.asyncio
async def test_reconcile_is_log_only_on_indexer_failure() -> None:
    repository = MemoryInMemoryRepository()
    async with repository.transaction() as tx:
        tx.insert_memory_record(_record("mem_1"))

    indexer = _RecordingIndexer(fail=True)
    count = await reconcile_pending_index(repository=repository, indexer=indexer)

    assert count == 0
    # record stays pending for the next startup
    assert [r.memory_id for r in await repository.list_memory_records_pending_index()] == [
        "mem_1"
    ]
