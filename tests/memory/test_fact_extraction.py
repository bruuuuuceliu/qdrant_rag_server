"""Fact-extraction tests: pure ``extract_facts`` unit tests + domain-level.

The domain-level tests exercise ``message.record`` end-to-end: user self-
disclosures become versioned, user-scoped ``UserFact`` rows (FR-4), a later
conflicting disclosure supersedes the prior active fact (FR-4.5), replays do
not re-extract, assistant turns produce no facts, and an extractor failure
never breaks ``message.record``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from memory_service.compression import CondenseV1Policy
from memory_service.domain_handler import MemoryDomainHandler
from memory_service.facts import extract_facts
from memory_service.identity import FakeIdentitySource
from memory_service.indexer import FakeMemoryIndexer
from memory_service.repository import PostgresMemoryRepository
from memory_service.searcher import FakeMemorySearcher
from shared.contracts import MessageEnvelope
from shared.service_auth import ServiceAuthSettings

from .conftest import AUDIENCE, ISSUER, SIGNING_KEY, command


def _result(envelope: MessageEnvelope) -> dict[str, Any]:
    return envelope.payload["result"]


# --- pure extract_facts unit tests ------------------------------------------


def test_name_variants() -> None:
    assert extract_facts("my name is Bruce") == [
        {"fact_type": "name", "subject": "name", "text": "Bruce"}
    ]
    assert extract_facts("call me Tom")[0]["text"] == "Tom"
    assert extract_facts("you can call me Jerry")[0]["text"] == "Jerry"
    assert extract_facts("i'm called Sam")[0]["text"] == "Sam"
    assert extract_facts("I am called Sam")[0]["text"] == "Sam"
    assert extract_facts("My name is Bruce Lee")[0]["text"] == "Bruce Lee"


def test_preference_variants() -> None:
    assert extract_facts("I like gluten-free pasta") == [
        {"fact_type": "preference", "subject": "gluten-free pasta", "text": "gluten-free pasta"}
    ]
    assert extract_facts("i love pizza")[0]["text"] == "pizza"
    assert extract_facts("i really enjoy hiking")[0]["text"] == "hiking"
    assert extract_facts("i prefer tea over coffee") == [
        {"fact_type": "preference", "subject": "tea", "text": "tea"}
    ]
    assert extract_facts("i don't like mushrooms") == [
        {"fact_type": "preference", "subject": "mushrooms", "text": "does not like mushrooms"}
    ]
    assert extract_facts("i do not like cilantro")[0]["text"] == "does not like cilantro"
    assert extract_facts("my favorite food is sushi") == [
        {"fact_type": "preference", "subject": "food", "text": "sushi"}
    ]
    assert extract_facts("my favourite movie is Inception")[0]["text"] == "Inception"


def test_location_variants() -> None:
    for content in (
        "I live in Paris",
        "i'm based in London",
        "i am based in London",
        "i'm from New York",
        "my city is Seattle",
    ):
        facts = extract_facts(content)
        assert len(facts) == 1
        assert facts[0]["fact_type"] == "location"
        assert facts[0]["subject"] == "location"
        assert facts[0]["text"]


def test_occupation_variants() -> None:
    assert extract_facts("i work as a software engineer") == [
        {"fact_type": "occupation", "subject": "role", "text": "software engineer"}
    ]
    assert extract_facts("i work at Google") == [
        {"fact_type": "occupation", "subject": "employer", "text": "Google"}
    ]
    assert extract_facts("i work for Acme Corp")[0]["text"] == "Acme Corp"
    assert extract_facts("i'm a data scientist")[0]["text"] == "data scientist"
    assert extract_facts("i am a product designer")[0]["text"] == "product designer"


def test_contact_variants() -> None:
    assert extract_facts("my email is bruce@example.com") == [
        {"fact_type": "contact", "subject": "email", "text": "bruce@example.com"}
    ]
    assert extract_facts("my email address is bruce@example.com.")[0]["text"] == "bruce@example.com"
    assert extract_facts("my phone number is 555-123-4567") == [
        {"fact_type": "contact", "subject": "phone", "text": "555-123-4567"}
    ]
    assert extract_facts("my cell is +1 555-123-4567")[0]["text"] == "+1 555-123-4567"


def test_boundary_negatives() -> None:
    # Questions are never extracted.
    assert extract_facts("do i like pasta?") == []
    assert extract_facts("do I like pasta") == []
    assert extract_facts("Do you like pasta?") == []
    assert extract_facts("I like pasta, do you?") == []
    # Third-party statements are not first-person self-disclosures.
    assert extract_facts("my friend's name is Bob") == []
    assert extract_facts("his name is Bob") == []
    # Non-name "call me" uses.
    assert extract_facts("call me when you get home") == []
    assert extract_facts("call me back") == []
    assert extract_facts("my name is not important") == []
    # Non-occupation "i'm a ..." phrases.
    assert extract_facts("i'm a big fan of pizza") == []
    # Bare-pronoun preference objects carry no durable signal.
    assert extract_facts("i love it") == []
    assert extract_facts("i like this") == []
    # Non-self-disclosure messages.
    assert extract_facts("what time is it?") == []
    assert extract_facts("I am 30 years old") == []


def test_preference_clause_boundaries() -> None:
    # Contrastive/conjunctive clauses are cut so the object stays the topic.
    assert extract_facts("i prefer tea over coffee")[0]["text"] == "tea"
    assert extract_facts("i like pasta, it is tasty")[0]["text"] == "pasta"
    assert extract_facts("i like pasta but not cheese")[0]["text"] == "pasta"
    # A coordinated object ("and") is kept as a single preference object.
    assert extract_facts("i like dogs and cats")[0]["text"] == "dogs and cats"
    # Different topics in one message remain separate facts.
    mixed = extract_facts("i like pizza, i don't like mushrooms")
    assert {f["subject"] for f in mixed} == {"pizza", "mushrooms"}


def test_trimming_and_dedup() -> None:
    # Trailing punctuation is stripped; internal whitespace collapsed.
    fact = extract_facts("my name is   Bruce .")[0]
    assert fact["text"] == "Bruce"
    # Long values are capped.
    long = "x" * 500
    assert len(extract_facts(f"my name is {long}")[0]["text"]) <= 200
    # Repeated disclosures in one message dedupe to one fact per (type, subject).
    name_facts = extract_facts("my name is Bruce, call me Tom")
    assert len(name_facts) == 1
    assert name_facts[0]["text"] == "Bruce"
    pref_facts = extract_facts("i like pizza and i love pizza")
    assert len(pref_facts) == 1
    assert pref_facts[0]["text"] == "pizza"
    # Different subjects within a message are kept separately.
    mixed = extract_facts("i like pizza, i don't like mushrooms")
    assert {f["subject"] for f in mixed} == {"pizza", "mushrooms"}


def test_single_word_occupations() -> None:
    # A role whose whole word is a suffix ("doctor") must still match — the
    # head before the suffix is optional, not mandatory (regression).
    for text in (
        "i'm a doctor",
        "i'm a student",
        "i'm a nurse",
        "i'm an engineer",
        "i'm a teacher",
        "i'm a lawyer",
    ):
        facts = extract_facts(text)
        assert facts, f"expected an occupation fact for {text!r}"
        assert facts[0]["fact_type"] == "occupation"
        assert facts[0]["subject"] == "role"
    # A non-occupation phrase that merely ends in a role word is still captured
    # ("a big engineer" is an occupation); a phrase with no role word is not.
    assert extract_facts("i'm a software engineer")[0]["text"] == "software engineer"
    assert extract_facts("i'm a big fan of pizza") == []


def test_abbreviation_does_not_split_name() -> None:
    # "my name is Mr. Smith" must not split at the abbreviation period and
    # capture only "Mr" (regression).
    facts = extract_facts("my name is Mr. Smith")
    assert len(facts) == 1
    assert facts[0]["fact_type"] == "name"
    assert facts[0]["text"] == "Mr. Smith"
    assert extract_facts("my name is Dr. Jane Doe")[0]["text"] == "Dr. Jane Doe"


def test_name_trailing_question_word_is_cut() -> None:
    # "my name is Bruce what is yours" must yield "Bruce", not "Bruce what"
    # (regression: missing question words in the name bad-word lists).
    facts = extract_facts("my name is Bruce what is yours")
    assert facts[0]["text"] == "Bruce"
    assert extract_facts("my name is Sam who are you")[0]["text"] == "Sam"


def test_pronoun_preference_objects_skipped() -> None:
    # "i like you"/"i like it" carry no durable signal and must not become
    # preference facts.
    assert extract_facts("i like you") == []
    assert extract_facts("i like it") == []


# --- domain-handler message.record tests ------------------------------------


async def _record(
    handler,
    content: str,
    *,
    role: str = "user",
    message_id: str = "msg_1",
    session_id: str = "con_1",
    sequence_number: int = 1,
) -> dict[str, Any]:
    await handler.handle(
        command("session.start", {"session_id": session_id, "agent_id": "agent_1"})
    )
    return _result(
        await handler.handle(
            command(
                "message.record",
                {
                    "message_id": message_id,
                    "session_id": session_id,
                    "agent_id": "agent_1",
                    "role": role,
                    "sequence_number": sequence_number,
                    "content": content,
                },
            )
        )
    )


async def test_message_record_creates_fact(seeded_handler) -> None:
    handler = seeded_handler
    result = await _record(handler, "my name is Bruce")
    assert result["recorded"] is True
    extracted = result["extracted_facts"]
    assert len(extracted) == 1
    fact = extracted[0]
    assert fact["fact_type"] == "name"
    assert fact["subject"] == "name"
    assert fact["text"] == "Bruce"
    assert fact["status"] == "active"
    assert fact["version"] == 1
    assert fact["user_id"] == "user_1"
    assert fact["updated_by"] == "agent_1"
    assert fact["source_message_id"] == "msg_1"

    stored = await handler._repository.list_active_facts("user_1")
    assert len(stored) == 1
    assert stored[0].fact_type == "name"
    assert stored[0].text == "Bruce"


async def test_conflicting_disclosure_supersedes(seeded_handler) -> None:
    handler = seeded_handler
    first = await _record(handler, "my name is Bruce", message_id="msg_1")
    assert first["extracted_facts"][0]["version"] == 1

    second = await _record(handler, "call me Tom", message_id="msg_2", sequence_number=2)
    assert second["extracted_facts"][0]["text"] == "Tom"
    assert second["extracted_facts"][0]["version"] == 2

    active = await handler._repository.list_active_facts("user_1")
    assert len(active) == 1
    assert active[0].text == "Tom"
    assert active[0].status == "active"
    assert active[0].version == 2

    all_facts = await handler._repository.list_facts("user_1", include_inactive=True)
    bruce = next(f for f in all_facts if f.text == "Bruce")
    assert bruce.status == "inactive"
    assert bruce.superseded_by == active[0].fact_id


async def test_replay_same_message_id_does_not_reextract(seeded_handler) -> None:
    handler = seeded_handler
    request = {
        "message_id": "msg_1",
        "session_id": "con_1",
        "agent_id": "agent_1",
        "role": "user",
        "sequence_number": 1,
        "content": "my name is Bruce",
    }
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    first = _result(await handler.handle(command("message.record", request)))
    assert first["recorded"] is True
    assert len(first["extracted_facts"]) == 1

    second = _result(await handler.handle(command("message.record", request)))
    assert second["recorded"] is False
    assert "extracted_facts" not in second

    active = await handler._repository.list_active_facts("user_1")
    assert len(active) == 1  # no duplicate fact row from the replay


async def test_assistant_message_produces_no_facts(seeded_handler) -> None:
    handler = seeded_handler
    result = await _record(handler, "my name is Bruce", role="assistant")
    assert result["recorded"] is True
    assert "extracted_facts" not in result
    assert await handler._repository.list_active_facts("user_1") == []


async def test_extractor_failure_does_not_break_message_record(
    seeded_handler, monkeypatch
) -> None:
    import memory_service.domain_handler as domain_handler

    def boom(content: str) -> list[dict[str, str]]:
        raise RuntimeError("extractor boom")

    monkeypatch.setattr(domain_handler, "extract_facts", boom)
    handler = seeded_handler
    result = await _record(handler, "my name is Bruce")
    assert result["recorded"] is True
    assert result["message"]["content"] == "my name is Bruce"
    assert "extracted_facts" not in result


async def test_extracted_facts_retrievable_via_lookup(seeded_handler) -> None:
    handler = seeded_handler
    await _record(handler, "my name is Bruce and i like gluten-free pasta")
    lookup = _result(
        await handler.handle(
            command("memory.lookup", {"query": "Bruce gluten", "sources": ["user_profile_facts"]})
        )
    )
    hits = lookup["results"]["user_profile_facts"]
    texts = [item["text"] for item in hits]
    assert any("Bruce" in text for text in texts)


# --- Postgres-backed message.record regression (review blocker) --------------
# The blocker: fact writes used to run INSIDE the message.record transaction,
# so a supersession conflict (Postgres partial unique index) aborted the whole
# transaction and LOST the message. The fix moved fact persistence to its own
# per-fact transactions AFTER the message commits. These tests pin that a fact
# failure can never fail or lose a message, against real Postgres (skip when
# unreachable, via the session ``pg_dsn`` fixture).


def _pg_handler(repository: PostgresMemoryRepository) -> MemoryDomainHandler:
    return MemoryDomainHandler(
        repository=repository,
        compression=CondenseV1Policy(),
        indexer=FakeMemoryIndexer(),
        searcher=FakeMemorySearcher(),
        identity_source=FakeIdentitySource(repository),
        producer=None,
        service_auth=ServiceAuthSettings(
            signing_key=SIGNING_KEY,
            issuer=ISSUER,
            audience=AUDIENCE,
            allowed_services=("conversation-server",),
        ),
        memory_collection_name="agent_memory",
        documents_collection_name="agent_documents",
    )


@pytest.fixture
async def pg_handler(pg_dsn: str) -> MemoryDomainHandler:
    repository = PostgresMemoryRepository(pg_dsn)
    await repository.initialize()
    async with repository._pool.connection() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS messages, memory_records, user_facts,"
            " idempotency_records, sessions, user_profiles CASCADE"
        )
    await repository.initialize()
    handler = _pg_handler(repository)
    await handler._identity_source.seed()
    yield handler
    await repository.close()


@pytest.mark.asyncio
async def test_pg_message_record_persists_message_and_fact(pg_handler) -> None:
    handler = pg_handler
    result = await _record(
        handler, "my name is Bruce", message_id="pg_msg_1", session_id="pg_con_1"
    )
    assert result["recorded"] is True
    extracted = result.get("extracted_facts") or []
    assert len(extracted) == 1
    assert extracted[0]["fact_type"] == "name"
    assert extracted[0]["text"] == "Bruce"
    # The message row exists independently of the fact write.
    repo = handler._repository
    msg = await repo.get_message("user_1", "pg_msg_1")
    assert msg is not None and msg.content == "my name is Bruce"
    facts = await repo.list_active_facts("user_1")
    assert len(facts) == 1 and facts[0].text == "Bruce"


@pytest.mark.asyncio
async def test_pg_concurrent_fact_conflict_never_loses_message(pg_dsn: str) -> None:
    # Two concurrent message.record calls extracting the same (fact_type,
    # subject) race on the partial unique index. The loser's fact write fails,
    # but its message MUST still be persisted — the whole point of moving fact
    # writes out of the message transaction.
    barrier = threading.Barrier(3)
    results: list[tuple[str, bool]] = []

    def worker(session_id: str, message_id: str) -> None:
        async def run() -> None:
            repository = PostgresMemoryRepository(pg_dsn)
            await repository.initialize()
            handler = _pg_handler(repository)
            await handler._identity_source.seed()
            try:
                barrier.wait()
                await handler.handle(
                    command(
                        "session.start",
                        {"session_id": session_id, "agent_id": "agent_1"},
                    )
                )
                res = _result(
                    await handler.handle(
                        command(
                            "message.record",
                            {
                                "message_id": message_id,
                                "session_id": session_id,
                                "agent_id": "agent_1",
                                "role": "user",
                                "sequence_number": 1,
                                "content": "my name is Bruce",
                            },
                        )
                    )
                )
                results.append((session_id, bool(res.get("recorded"))))
            finally:
                await repository.close()

        asyncio.run(run())

    threads = [
        threading.Thread(target=worker, args=("pg_c1", "pg_c_msg1")),
        threading.Thread(target=worker, args=("pg_c2", "pg_c_msg2")),
    ]
    for t in threads:
        t.start()
    barrier.wait()
    for t in threads:
        t.join()

    # Both messages must be recorded — a fact conflict must not lose either.
    assert sorted(results) == [("pg_c1", True), ("pg_c2", True)]
    # The durable store keeps exactly one active fact for (name, name).
    repository = PostgresMemoryRepository(pg_dsn)
    await repository.initialize()
    try:
        facts = await repository.list_active_facts("user_1")
        assert len(facts) == 1 and facts[0].text == "Bruce"
        for mid in ("pg_c_msg1", "pg_c_msg2"):
            assert await repository.get_message("user_1", mid) is not None
    finally:
        await repository.close()
