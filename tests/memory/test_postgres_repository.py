"""Postgres memory repository tests (run against the shared Postgres)."""

from __future__ import annotations

import asyncio
import os
import threading

import pytest

from memory_service.models import (
    IdempotencyRecord,
    MemoryMessage,
    MemoryRecord,
    MemorySession,
    UserFact,
    UserProfile,
    iso_utc_now,
)
from memory_service.repository import (
    FactSupersessionConflict,
    MemoryNotFoundError,
    PostgresMemoryRepository,
)


@pytest.fixture
async def repo(pg_dsn: str) -> PostgresMemoryRepository:
    repository = PostgresMemoryRepository(pg_dsn)
    await repository.initialize()
    async with repository._pool.connection() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS messages, memory_records, user_facts,"
            " idempotency_records, sessions, user_profiles CASCADE"
        )
    await repository.initialize()
    yield repository
    await repository.close()


@pytest.mark.asyncio
async def test_initialize_is_idempotent_and_accepts_document_kind(repo) -> None:
    now = iso_utc_now()
    async with repo.transaction() as tx:
        recorded = tx.insert_memory_record(
            MemoryRecord(
                memory_id="doc_1",
                owner_user_id="user_1",
                agent_id="agent_1",
                kind="document",
                content="handbook",
                collection_name="docs",
                metadata={"t": 1},
                created_at=now,
            )
        )
    assert recorded is True
    got = await repo.get_memory_record("user_1", "doc_1")
    assert got is not None and got.kind == "document"
    assert await repo.count_memory_records("user_1", "agent_1", kind="document") == 1


@pytest.mark.asyncio
async def test_upsert_session_is_idempotent_and_close_validates_owner(repo) -> None:
    now = iso_utc_now()
    async with repo.transaction() as tx:
        created = tx.upsert_session(
            MemorySession(
                session_id="s1",
                owner_user_id="user_1",
                agent_id="agent_1",
                status="active",
                started_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        replayed = tx.upsert_session(
            MemorySession(
                session_id="s1",
                owner_user_id="user_1",
                agent_id="agent_1",
                status="active",
                started_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    assert created is True and replayed is False
    assert await repo.session_owner("s1") == "user_1"
    async with repo.transaction() as tx:
        closed, changed = tx.close_session(
            owner_user_id="user_1", session_id="s1", closed_at=now
        )
    assert changed is True and closed.status == "closed"
    with pytest.raises(MemoryNotFoundError):
        async with repo.transaction() as tx:
            tx.close_session(owner_user_id="other", session_id="s1", closed_at=now)


@pytest.mark.asyncio
async def test_duplicate_message_sequence_returns_false_and_continues(repo) -> None:
    now = iso_utc_now()
    async with repo.transaction() as tx:
        assert tx.insert_message(
            MemoryMessage(
                message_id="m1",
                session_id="s1",
                owner_user_id="user_1",
                agent_id="agent_1",
                role="user",
                sequence_number=1,
                content="hi",
                created_at=now,
            )
        ) is True
        # duplicate (session_id, sequence_number) is rejected but the
        # transaction stays usable
        assert tx.insert_message(
            MemoryMessage(
                message_id="m2",
                session_id="s1",
                owner_user_id="user_1",
                agent_id="agent_1",
                role="user",
                sequence_number=1,
                content="dup",
                created_at=now,
            )
        ) is False
        tx.store_idempotent(
            IdempotencyRecord(
                idempotency_key="k1",
                operation="op",
                request_hash="h",
                result={},
                owner_user_id="user_1",
                created_at=now,
            )
        )
    assert await repo.count_messages("user_1", "agent_1") == 1


@pytest.mark.asyncio
async def test_pending_index_roundtrip(repo) -> None:
    now = iso_utc_now()
    for memory_id in ("mem_1", "mem_2"):
        async with repo.transaction() as tx:
            tx.insert_memory_record(
                MemoryRecord(
                    memory_id=memory_id,
                    owner_user_id="user_1",
                    agent_id="agent_1",
                    kind="message",
                    content="hello",
                    created_at=now,
                )
            )
    pending = {r.memory_id for r in await repo.list_memory_records_pending_index()}
    assert pending == {"mem_1", "mem_2"}
    assert await repo.mark_memory_records_indexed(["mem_1"]) == 1
    pending = {r.memory_id for r in await repo.list_memory_records_pending_index()}
    assert pending == {"mem_2"}


@pytest.mark.asyncio
async def test_fact_supersession_and_profile_without_row(repo) -> None:
    now = iso_utc_now()
    # fact write does not require a prior profile row (FK parity)
    async with repo.transaction() as tx:
        tx.insert_fact(
            UserFact(
                fact_id="f1",
                user_id="user_1",
                fact_type="pref",
                subject="theme",
                text="dark",
                status="active",
                version=1,
                updated_by="agent_1",
                created_at=now,
                updated_at=now,
            )
        )
    async with repo.transaction() as tx:
        superseded, inserted = tx.supersede_fact(
            user_id="user_1",
            fact_type="pref",
            subject="theme",
            new_fact=UserFact(
                fact_id="f2",
                user_id="user_1",
                fact_type="pref",
                subject="theme",
                text="light",
                status="active",
                version=0,
                updated_by="agent_1",
                created_at=now,
                updated_at=now,
            ),
        )
    assert [f.fact_id for f in superseded] == ["f1"]
    assert inserted.version == 2
    assert await repo.count_active_facts("user_1") == 1
    assert (await repo.get_fact("user_1", "f1")).superseded_by == "f2"

    async with repo.transaction() as tx:
        tx.upsert_profile(
            UserProfile(
                user_id="user_1",
                basic_info={"name": "b"},
                identity_revision=1,
                created_at=now,
                updated_at=now,
            )
        )
    profile = await repo.get_profile("user_1")
    assert profile is not None and profile.basic_info == {"name": "b"}


@pytest.mark.asyncio
async def test_concurrent_supersession_conflict(repo, pg_dsn: str) -> None:
    now = iso_utc_now()
    # Race on a fresh key with no pre-existing active fact: with nothing to
    # lock, both transactions reach the insert and the partial unique index
    # deterministically trips FactSupersessionConflict for the loser.
    subject = f"theme_{os.urandom(4).hex()}"
    dsn = pg_dsn
    barrier = threading.Barrier(3)
    outcomes: list[tuple[str, str]] = []

    def worker(fact_id: str) -> None:
        async def run() -> None:
            repository = PostgresMemoryRepository(dsn)
            await repository.initialize()
            try:
                barrier.wait()
                async with repository.transaction() as tx:
                    tx.supersede_fact(
                        user_id="user_1",
                        fact_type="pref",
                        subject=subject,
                        new_fact=UserFact(
                            fact_id=fact_id,
                            user_id="user_1",
                            fact_type="pref",
                            subject=subject,
                            text="x",
                            status="active",
                            version=0,
                            updated_by="agent_1",
                            created_at=now,
                            updated_at=now,
                        ),
                    )
                outcomes.append((fact_id, "ok"))
            except FactSupersessionConflict:
                outcomes.append((fact_id, "conflict"))
            finally:
                await repository.close()

        asyncio.run(run())

    threads = [
        threading.Thread(target=worker, args=(f"c{i}",)) for i in (1, 2)
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) in (
        [("c1", "conflict"), ("c2", "ok")],
        [("c1", "ok"), ("c2", "conflict")],
    ), outcomes

    repository = PostgresMemoryRepository(dsn)
    await repository.initialize()
    assert await repository.count_active_facts("user_1") == 1
    await repository.close()


@pytest.mark.asyncio
async def test_read_back_surface(repo) -> None:
    """The read-side repository surface round-trips stored documents: sessions,
    messages, memory records, summaries, facts, and idempotency records all come
    back through their list/get methods."""
    now = iso_utc_now()
    async with repo.transaction() as tx:
        tx.upsert_session(
            MemorySession(
                session_id="s1",
                owner_user_id="user_1",
                agent_id="agent_1",
                status="active",
                started_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        tx.insert_message(
            MemoryMessage(
                message_id="m1",
                session_id="s1",
                owner_user_id="user_1",
                agent_id="agent_1",
                role="user",
                sequence_number=1,
                content="first",
                metadata={"n": 1},
                created_at=now,
            )
        )
        tx.insert_message(
            MemoryMessage(
                message_id="m2",
                session_id="s1",
                owner_user_id="user_1",
                agent_id="agent_1",
                role="assistant",
                sequence_number=2,
                content="second",
                created_at=now,
            )
        )
        tx.insert_memory_record(
            MemoryRecord(
                memory_id="sum_1",
                session_id="s1",
                owner_user_id="user_1",
                agent_id="agent_1",
                kind="compression_summary",
                content="condensed",
                covered_from=1,
                covered_to=2,
                created_at=now,
            )
        )
        tx.insert_memory_record(
            MemoryRecord(
                memory_id="doc_1",
                owner_user_id="user_1",
                agent_id="agent_1",
                kind="document",
                content="handbook",
                collection_name="docs",
                metadata={"t": 1},
                created_at=now,
            )
        )
        tx.insert_fact(
            UserFact(
                fact_id="f1",
                user_id="user_1",
                fact_type="pref",
                subject="theme",
                text="dark",
                status="active",
                version=1,
                updated_by="agent_1",
                created_at=now,
                updated_at=now,
            )
        )
        tx.supersede_fact(
            user_id="user_1",
            fact_type="pref",
            subject="theme",
            new_fact=UserFact(
                fact_id="f2",
                user_id="user_1",
                fact_type="pref",
                subject="theme",
                text="light",
                status="active",
                version=0,
                updated_by="agent_1",
                created_at=now,
                updated_at=now,
            ),
        )
        tx.store_idempotent(
            IdempotencyRecord(
                idempotency_key="k1",
                operation="op",
                request_hash="h",
                result={"ok": True},
                owner_user_id="user_1",
                created_at=now,
            )
        )

    session = await repo.get_session("user_1", "s1")
    assert session is not None and session.status == "active"
    assert await repo.get_session("other", "s1") is None

    assert await repo.get_message("user_1", "m1") is not None
    assert await repo.get_message("other", "m1") is None
    assert [m.message_id for m in await repo.list_session_messages("user_1", "s1")] == [
        "m1",
        "m2",
    ]
    assert [m.message_id for m in await repo.list_messages("user_1", "agent_1")] == [
        "m1",
        "m2",
    ]

    summaries = await repo.list_session_summaries("user_1", "s1")
    assert [r.memory_id for r in summaries] == ["sum_1"]
    assert summaries[0].covered_from == 1 and summaries[0].covered_to == 2

    records = await repo.list_memory_records("user_1", "agent_1")
    assert {r.memory_id for r in records} == {"sum_1", "doc_1"}
    doc = next(r for r in records if r.kind == "document")
    assert doc.collection_name == "docs" and doc.metadata == {"t": 1}

    assert [f.fact_id for f in await repo.list_active_facts("user_1")] == ["f2"]
    all_facts = await repo.list_facts("user_1", include_inactive=True)
    assert {f.fact_id for f in all_facts} == {"f1", "f2"}
    assert await repo.list_facts("user_1") == [
        f for f in all_facts if f.status == "active"
    ]

    async with repo.transaction() as tx:
        idem = tx.get_idempotent("k1", owner_user_id="user_1")
    assert idem is not None and idem.result == {"ok": True}
