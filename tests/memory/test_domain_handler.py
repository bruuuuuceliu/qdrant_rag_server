"""Memory domain-handler tests covering requirements AC-1..16."""

from __future__ import annotations

from typing import Any

import pytest

from memory_service.repository import (
    FactSupersessionConflict,
    IdempotencyConflictError,
    MemoryInMemoryRepository,
)
from shared.contracts import MessageEnvelope, MessageType, TOPICS
from shared.service_auth import ServiceAuthSettings

from .conftest import command, request_hash, token


def _result(envelope: MessageEnvelope) -> dict[str, Any]:
    return envelope.payload["result"]


# --- FR-1 sessions and messages --------------------------------------------


async def test_ac1_session_start_creates_and_is_idempotent(seeded_handler) -> None:
    handler = seeded_handler
    first = await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    assert first.message_type == MessageType.DOMAIN_RESULT
    result = _result(first)
    assert result["created"] is True
    assert result["session"]["status"] == "active"

    second = await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    result2 = _result(second)
    assert result2["created"] is False
    assert result2["replayed"] is True
    assert result2["session"]["session_id"] == "con_1"


async def test_ac2_message_record_persists_and_dedupes(seeded_handler) -> None:
    handler = seeded_handler
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    request = {
        "message_id": "msg_1",
        "session_id": "con_1",
        "agent_id": "agent_1",
        "role": "user",
        "sequence_number": 1,
        "content": "Hello",
    }
    first = await handler.handle(command("message.record", request))
    result = _result(first)
    assert result["recorded"] is True
    assert result["message"]["owner_user_id"] == "user_1"
    assert result["message"]["sequence_number"] == 1

    second = await handler.handle(command("message.record", request))
    assert _result(second)["recorded"] is False


async def test_ac3_messages_stored_in_sequence_order(seeded_handler) -> None:
    handler = seeded_handler
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    for seq, content in ((1, "first"), (2, "second"), (3, "third")):
        await handler.handle(
            command(
                "message.record",
                {
                    "message_id": f"msg_{seq}",
                    "session_id": "con_1",
                    "agent_id": "agent_1",
                    "role": "user" if seq % 2 else "assistant",
                    "sequence_number": seq,
                    "content": content,
                },
            )
        )
    messages = await handler._repository.list_session_messages("user_1", "con_1")
    assert [m.sequence_number for m in messages] == [1, 2, 3]


async def test_ac4_closed_session_still_searchable(seeded_handler) -> None:
    handler = seeded_handler
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    await handler.handle(
        command("message.record", {
            "message_id": "msg_1", "session_id": "con_1", "agent_id": "agent_1",
            "role": "user", "sequence_number": 1, "content": "gluten allergy",
        })
    )
    close = await handler.handle(command("session.close", {"session_id": "con_1"}))
    assert _result(close)["changed"] is True
    assert _result(close)["session"]["status"] == "closed"

    lookup = await handler.handle(
        command("memory.lookup", {"query": "gluten", "sources": ["chat_history"]})
    )
    assert _result(lookup)["results"]["chat_history"] is not None


# --- FR-2 compression ------------------------------------------------------


async def test_ac5_compress_returns_and_persists_summary(seeded_handler) -> None:
    handler = seeded_handler
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    for seq in range(1, 6):
        await handler.handle(
            command("message.record", {
                "message_id": f"msg_{seq}", "session_id": "con_1", "agent_id": "agent_1",
                "role": "user", "sequence_number": seq, "content": f"Message {seq} here.",
            })
        )
    result = await handler.handle(
        command("memory.compress", {"session_id": "con_1", "start_sequence": 1, "end_sequence": 5})
    )
    payload = _result(result)
    assert payload["condensed_context"]
    assert payload["memory_id"].startswith("mem_sum_")
    assert payload["covered_range"] == {"from": 1, "to": 5}

    records = await handler._repository.list_memory_records("user_1", "agent_1")
    summaries = [r for r in records if r.kind == "compression_summary"]
    assert len(summaries) == 1
    assert summaries[0].covered_from == 1
    assert summaries[0].covered_to == 5


async def test_ac6_compress_same_span_is_deduplicated(seeded_handler) -> None:
    handler = seeded_handler
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    for seq in range(1, 4):
        await handler.handle(
            command("message.record", {
                "message_id": f"msg_{seq}", "session_id": "con_1", "agent_id": "agent_1",
                "role": "user", "sequence_number": seq, "content": f"Line {seq}.",
            })
        )
    request = {"session_id": "con_1", "start_sequence": 1, "end_sequence": 3}
    first = _result(await handler.handle(command("memory.compress", request)))
    second = _result(await handler.handle(command("memory.compress", request)))
    assert first["memory_id"] == second["memory_id"]
    assert second["replayed"] is True

    records = await handler._repository.list_memory_records("user_1", "agent_1")
    assert len([r for r in records if r.kind == "compression_summary"]) == 1


# --- FR-3 cross-source retrieval -------------------------------------------


async def test_ac7_lookup_returns_per_source_results_and_consulted(seeded_handler) -> None:
    handler = seeded_handler
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    await handler.handle(
        command("message.record", {
            "message_id": "msg_1", "session_id": "con_1", "agent_id": "agent_1",
            "role": "user", "sequence_number": 1, "content": "user avoids gluten",
        })
    )
    # seed a fact via profile.update
    await handler.handle(
        command("profile.update", {"fact_type": "dietary", "subject": "", "text": "avoids gluten"})
    )
    result = _result(await handler.handle(command("memory.lookup", {"query": "gluten"})))
    assert set(result["sources"]) == {"chat_history", "documents", "user_profile_facts"}
    # B1: documents is now a real source — every requested source is consulted.
    # No documents have been ingested in this test, so the documents result is
    # empty (count-gate short-circuits before the searcher is called).
    assert result["consulted"] == {
        "chat_history": True, "documents": True, "user_profile_facts": True
    }
    assert result["results"]["documents"] == []
    assert result["results"]["user_profile_facts"], "fact source should match"
    for source, items in result["results"].items():
        for item in items:
            assert item["source"] == source
            assert {"source", "source_id", "text", "score"} <= set(item)


async def test_ac8_lookup_scoped_to_verified_owner(seeded_handler) -> None:
    handler = seeded_handler
    # user_2 records a session + message
    await handler.handle(
        command("session.start", {"session_id": "con_u2", "agent_id": "agent_1"}, actor_user_id="user_2")
    )
    await handler.handle(
        command("message.record", {
            "message_id": "msg_u2", "session_id": "con_u2", "agent_id": "agent_1",
            "role": "user", "sequence_number": 1, "content": "secret of user 2",
        }, actor_user_id="user_2")
    )
    # user_1 looks up — must not see user_2's content
    result = _result(await handler.handle(command("memory.lookup", {"query": "secret"})))
    chat_items = result["results"]["chat_history"]
    assert all(item.get("session_id") != "con_u2" for item in chat_items)


# --- B1 owner-scoped documents source --------------------------------------


async def test_documents_ingest_persists_kind_document(seeded_handler) -> None:
    handler = seeded_handler
    result = _result(
        await handler.handle(
            command(
                "memory.documents.ingest",
                {"documents": [{"doc_id": "doc_1", "text": "user handbook on refunds"}]},
            )
        )
    )
    assert result["documents"][0]["recorded"] is True
    assert result["documents"][0]["indexed"] is True
    assert result["collection_name"] == handler._documents_collection_name

    records = await handler._repository.list_memory_records("user_1", "agent_1")
    docs = [record for record in records if record.kind == "document"]
    assert len(docs) == 1
    assert docs[0].memory_id == "doc_1"
    assert docs[0].owner_user_id == "user_1"
    assert docs[0].agent_id == "agent_1"
    assert docs[0].content == "user handbook on refunds"

    # the fake indexer received the records targeting the documents collection
    assert handler._indexer.collections == [handler._documents_collection_name]


async def test_documents_ingest_dedupes_same_doc_id(seeded_handler) -> None:
    handler = seeded_handler
    first = _result(
        await handler.handle(
            command(
                "memory.documents.ingest",
                {"documents": [{"doc_id": "doc_1", "text": "user manual"}]},
            )
        )
    )
    assert first["documents"][0]["recorded"] is True
    # a different request (a distinct idempotency key changes the request hash,
    # hence the idempotency key) bypasses idempotency replay and hits the
    # memory_id dedup instead
    second = _result(
        await handler.handle(
            command(
                "memory.documents.ingest",
                {
                    "idempotency_key": "k2",
                    "documents": [{"doc_id": "doc_1", "text": "user manual"}],
                },
            )
        )
    )
    assert second["documents"][0]["recorded"] is False
    assert second["documents"][0]["indexed"] is False
    records = await handler._repository.list_memory_records("user_1", "agent_1")
    assert len([record for record in records if record.kind == "document"]) == 1


async def test_documents_sources_availability(seeded_handler) -> None:
    handler = seeded_handler
    before = _result(await handler.handle(command("memory.sources", {})))
    docs_before = next(s for s in before["sources"] if s["source"] == "documents")
    assert docs_before["available"] is False
    assert docs_before["count"] == 0

    await handler.handle(
        command(
            "memory.documents.ingest",
            {"documents": [{"doc_id": "doc_1", "text": "user manual"}]},
        )
    )
    after = _result(await handler.handle(command("memory.sources", {})))
    docs_after = next(s for s in after["sources"] if s["source"] == "documents")
    assert docs_after["available"] is True
    assert docs_after["count"] == 1


async def test_documents_lookup_scoped_to_owner(seeded_handler) -> None:
    handler = seeded_handler
    # user_2 ingests a document; user_1 must never see it
    await handler.handle(
        command(
            "memory.documents.ingest",
            {"documents": [{"doc_id": "doc_u2", "text": "user 2 private document"}]},
            actor_user_id="user_2",
        )
    )
    # user_1's documents lookup has no docs -> count-gate returns [] and the
    # searcher is not consulted at all for user_1
    result = _result(
        await handler.handle(
            command("memory.lookup", {"query": "private", "sources": ["documents"]})
        )
    )
    assert result["results"]["documents"] == []
    assert not any(call["owner_user_id"] == "user_1" for call in handler._searcher.calls)

    # once user_1 has a doc, the documents search runs scoped to user_1/agent_1
    # and is NEVER session-filtered
    await handler.handle(
        command(
            "memory.documents.ingest",
            {"documents": [{"doc_id": "doc_u1", "text": "user 1 manual"}]},
        )
    )
    lookup = _result(
        await handler.handle(
            command("memory.lookup", {"query": "manual", "sources": ["documents"]})
        )
    )
    assert lookup["consulted"] == {"documents": True}
    assert lookup["results"]["documents"] == []
    call = handler._searcher.calls[-1]
    assert call["owner_user_id"] == "user_1"
    assert call["agent_id"] == "agent_1"
    assert call["collection_name"] == handler._documents_collection_name
    assert call["session_ids"] == ()


# --- B1 review-fix regressions ---------------------------------------------


async def test_documents_ingest_accepts_long_text(seeded_handler) -> None:
    """B1-1: document bodies may exceed 2048 chars; only short identifier
    fields keep the 2048 cap."""
    handler = seeded_handler
    long_text = "long-text-content-" * 400  # ~7600 chars, no trailing space
    assert len(long_text) > 2048
    result = _result(
        await handler.handle(
            command(
                "memory.documents.ingest",
                {"documents": [{"doc_id": "doc_long", "text": long_text}]},
            )
        )
    )
    assert result["documents"][0]["recorded"] is True
    records = await handler._repository.list_memory_records("user_1", "agent_1")
    docs = [record for record in records if record.kind == "document"]
    assert docs[0].content == long_text

    # the 2048 cap still applies to the short doc_id field
    bad = await handler.handle(
        command(
            "memory.documents.ingest",
            {"documents": [{"doc_id": "x" * 2049, "text": "body"}]},
        )
    )
    assert _result(bad)["error"]["code"] == "validation_error"


async def test_documents_ingest_rejects_duplicate_doc_id_within_request(seeded_handler) -> None:
    """B1-3: duplicate doc_ids in one request are a validation error, so the
    per-doc recorded/status aggregation is unambiguous."""
    handler = seeded_handler
    result = await handler.handle(
        command(
            "memory.documents.ingest",
            {
                "documents": [
                    {"doc_id": "doc_x", "text": "first version"},
                    {"doc_id": "doc_x", "text": "second version"},
                ]
            },
        )
    )
    error = _result(result)["error"]
    assert error["code"] == "validation_error"
    assert "duplicate doc_id" in error["message"]
    # nothing was persisted
    records = await handler._repository.list_memory_records("user_1", "agent_1")
    assert [record for record in records if record.kind == "document"] == []


async def test_documents_ingest_wires_per_doc_metadata(seeded_handler) -> None:
    """B1-4: per-document metadata is stored on the record and reaches the
    indexer (and from there the Qdrant payload)."""
    handler = seeded_handler
    result = _result(
        await handler.handle(
            command(
                "memory.documents.ingest",
                {
                    "documents": [
                        {
                            "doc_id": "doc_m",
                            "text": "handbook",
                            "metadata": {"title": "Refund Handbook", "tags": ["finance"]},
                        }
                    ]
                },
            )
        )
    )
    assert result["documents"][0]["recorded"] is True
    # stored on the durable record
    records = await handler._repository.list_memory_records("user_1", "agent_1")
    doc = next(record for record in records if record.kind == "document")
    assert doc.metadata == {"title": "Refund Handbook", "tags": ["finance"]}
    # forwarded into the indexer payload
    indexed_record = handler._indexer.indexed[0][0]
    assert indexed_record.metadata == {"title": "Refund Handbook", "tags": ["finance"]}


async def test_documents_ingest_rejects_chat_memory_collection(seeded_handler) -> None:
    """B1-6: an explicit request collection_name equal to the chat-memory
    collection is rejected (trust-based guard against cross-collection mixing)."""
    handler = seeded_handler
    result = await handler.handle(
        command(
            "memory.documents.ingest",
            {
                "collection_name": "agent_memory",
                "documents": [{"doc_id": "doc_bad", "text": "never indexed here"}],
            },
        )
    )
    error = _result(result)["error"]
    assert error["code"] == "validation_error"
    assert "chat-memory collection" in error["message"]
    records = await handler._repository.list_memory_records("user_1", "agent_1")
    assert [record for record in records if record.kind == "document"] == []


async def test_lookup_resolves_ingest_time_document_collection(seeded_handler) -> None:
    """B1-2: ingest-time collection == lookup-time collection.

    Ingesting into a non-default collection is honored by memory.documents.ingest;
    memory.lookup resolves that stored collection from the rows, so the caller
    need not re-send it. A request-level collection_name optionally filters.
    """
    handler = seeded_handler
    ingest = _result(
        await handler.handle(
            command(
                "memory.documents.ingest",
                {
                    "collection_name": "custom_docs",
                    "documents": [{"doc_id": "doc_c", "text": "custom collection doc"}],
                },
            )
        )
    )
    assert ingest["collection_name"] == "custom_docs"
    assert ingest["documents"][0]["indexed"] is True

    # lookup without a collection_name resolves the stored ingest-time collection
    lookup = _result(
        await handler.handle(
            command("memory.lookup", {"query": "custom", "sources": ["documents"]})
        )
    )
    assert lookup["consulted"] == {"documents": True}
    call = handler._searcher.calls[-1]
    assert call["collection_name"] == "custom_docs"

    # an explicit matching collection_name still searches the same collection
    lookup_explicit = _result(
        await handler.handle(
            command(
                "memory.lookup",
                {"query": "custom", "sources": ["documents"], "collection_name": "custom_docs"},
            )
        )
    )
    assert lookup_explicit["results"]["documents"] == []
    assert handler._searcher.calls[-1]["collection_name"] == "custom_docs"

    # an explicit mismatched collection_name filters the resolved set to empty
    # (no documents were indexed into the default collection)
    lookup_mismatch = _result(
        await handler.handle(
            command(
                "memory.lookup",
                {
                    "query": "custom",
                    "sources": ["documents"],
                    "collection_name": handler._documents_collection_name,
                },
            )
        )
    )
    assert lookup_mismatch["results"]["documents"] == []
    assert lookup_mismatch["consulted"] == {"documents": True}


async def test_scope_rejects_actor_user_id_over_128(seeded_handler) -> None:
    """B3-2: owner_user_id (token actor_user_id) is bounded at 128 chars (§8)."""
    handler = seeded_handler
    long_user = "u" * 129
    result = await handler.handle(
        command(
            "session.start",
            {"session_id": "con_1", "agent_id": "agent_1"},
            actor_user_id=long_user,
        )
    )
    error = _result(result)["error"]
    assert error["code"] == "forbidden"
    assert "128" in error["message"]


# --- FR-4 profile and facts ------------------------------------------------


async def test_ac9_identity_event_creates_profile(handler) -> None:
    await handler._identity_source.on_user_registered(
        {
            "event_type": "identity.user.registered",
            "user_id": "user_1",
            "email": "u1@example.com",
            "display_name": "User One",
            "role": "tier_1",
            "account_status": "active",
        }
    )
    profile = await handler._repository.get_profile("user_1")
    assert profile is not None
    assert profile.basic_info["email"] == "u1@example.com"
    assert profile.basic_info["display_name"] == "User One"


async def test_ac10_profile_update_supersedes_fact(seeded_handler) -> None:
    handler = seeded_handler
    first = _result(
        await handler.handle(
            command("profile.update", {"fact_type": "dietary", "text": "avoids gluten"})
        )
    )
    second = _result(
        await handler.handle(
            command("profile.update", {"fact_type": "dietary", "text": "vegan"})
        )
    )
    assert second["fact"]["version"] == 2
    assert second["fact"]["status"] == "active"
    assert second["superseded"][0]["fact_id"] == first["fact"]["fact_id"]
    assert second["superseded"][0]["superseded_by"] == second["fact"]["fact_id"]

    active = await handler._repository.list_active_facts("user_1")
    assert len(active) == 1
    assert active[0].text == "vegan"


async def test_ac11_fact_writes_are_attributed(seeded_handler) -> None:
    handler = seeded_handler
    result = _result(
        await handler.handle(
            command(
                "profile.update",
                {
                    "fact_type": "contact_preference",
                    "text": "email",
                    "source_message_id": "msg_9",
                },
            )
        )
    )
    fact = result["fact"]
    assert fact["updated_by"] == "agent_1"
    assert fact["source_message_id"] == "msg_9"
    assert fact["created_at"] and fact["updated_at"]


async def test_ac12_basic_info_reconcile_conflict(seeded_handler) -> None:
    handler = seeded_handler
    await handler._identity_source.on_user_registered(
        {
            "event_type": "identity.user.registered",
            "user_id": "user_1",
            "email": "authoritative@example.com",
            "display_name": "User One",
            "role": "tier_1",
            "account_status": "active",
        }
    )
    result = _result(
        await handler.handle(
            command(
                "profile.update",
                {
                    "fact_type": "preference",
                    "text": "email",
                    "basic_info_fields": {"email": "user-claimed@example.com"},
                },
            )
        )
    )
    # account data is authoritative -> conflict, not applied
    assert "email" in result["basic_info"]["account_authoritative_conflicts"]
    profile = await handler._repository.get_profile("user_1")
    assert profile.basic_info["email"] == "authoritative@example.com"


# --- idempotency -----------------------------------------------------------


async def test_ac13_idempotency_replay_and_conflict(seeded_handler) -> None:
    handler = seeded_handler
    # Use profile.update: it has no natural-dedup pre-check, so the idempotency
    # table is the sole replay guard.
    request = {"fact_type": "preference", "text": "email", "idempotency_key": "op-1"}
    first = _result(await handler.handle(command("profile.update", request)))
    assert first["fact"]["text"] == "email"

    # replay same key + same payload -> stored result returned
    replay = _result(await handler.handle(command("profile.update", request)))
    assert replay["fact"]["text"] == "email"

    # same key + different payload -> conflict
    changed = dict(request)
    changed["text"] = "phone"
    conflict = await handler.handle(command("profile.update", changed))
    assert _result(conflict)["ok"] is False
    assert _result(conflict)["error"]["code"] == "conflict"


async def test_ac14_reply_echoes_correlation_and_operation(seeded_handler) -> None:
    handler = seeded_handler
    envelope = await handler.handle(
        command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}, correlation_id="corr-xyz")
    )
    assert envelope.correlation_id == "corr-xyz"
    assert envelope.payload["operation"] == "session.start"


async def test_ac15_error_mapping_and_retryable(seeded_handler) -> None:
    handler = seeded_handler
    # validation error: missing session_id
    bad = await handler.handle(command("session.start", {"agent_id": "agent_1"}))
    assert _result(bad)["error"]["code"] == "validation_error"
    assert _result(bad)["error"]["retryable"] is False

    # unauthorized: bad token
    unauth = await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}, headers={"Authorization": "Bearer bad"}))
    assert _result(unauth)["error"]["code"] == "unauthorized"


async def test_ac16_fake_mode_full_set_without_broker(seeded_handler) -> None:
    """Full operation set runs with in-memory repo + fakes (no broker)."""
    handler = seeded_handler
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    await handler.handle(
        command("message.record", {
            "message_id": "msg_1", "session_id": "con_1", "agent_id": "agent_1",
            "role": "user", "sequence_number": 1, "content": "Hello there",
        })
    )
    await handler.handle(command("session.close", {"session_id": "con_1"}))
    await handler.handle(
        command("memory.compress", {"session_id": "con_1", "start_sequence": 1, "end_sequence": 1})
    )
    await handler.handle(command("memory.lookup", {"query": "hello"}))
    await handler.handle(command("memory.sources", {}))
    await handler.handle(command("profile.read", {}))
    await handler.handle(command("profile.update", {"fact_type": "pref", "text": "x"}))
    assert True


# --- scoping / auth edge cases ---------------------------------------------


async def test_scope_forbidden_when_service_not_allowed(seeded_handler, auth_settings) -> None:
    handler = seeded_handler
    env = await handler.handle(
        command("session.start", {"session_id": "con_1", "agent_id": "agent_1"})
    )
    # re-mint token as an unlisted service
    bad = await handler.handle(
        command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}, headers={"Authorization": f"Bearer {token(service='rogue')}"})
    )
    assert _result(bad)["error"]["code"] == "forbidden"


async def test_cross_owner_session_rejected(seeded_handler) -> None:
    handler = seeded_handler
    await handler.handle(
        command("session.start", {"session_id": "con_shared", "agent_id": "agent_1"}, actor_user_id="user_1")
    )
    # user_2 tries to start/claim the same session id -> forbidden
    result = await handler.handle(
        command("session.start", {"session_id": "con_shared", "agent_id": "agent_1"}, actor_user_id="user_2")
    )
    assert _result(result)["error"]["code"] == "forbidden"


# --- Follow-up A: long-turn cap regression ----------------------------------
#
# QA concern #1 (Sprint B): message.record content and memory.lookup query were
# capped at 2048 chars via _require_str, so a >2048-char user turn was silently
# NOT recorded and the B2 lookup (the current user message content) failed with
# validation_error -> the retrieved-context block silently disappeared. The fix
# truncates both deterministically to the 2048 prefix (never rejects).


async def test_message_record_truncates_long_content(seeded_handler) -> None:
    """Follow-up A: a >2048-char message is recorded, not validation_error-dropped.

    The stored content is deterministically truncated to the documented 2048-char
    prefix (the exact string prefix is kept), so the session's message history is
    intact and the bounded text flows through the index hand-off unchanged.
    """
    handler = seeded_handler
    await handler.handle(command("session.start", {"session_id": "con_1", "agent_id": "agent_1"}))
    long_content = "long-turn-" * 500  # ~4500 chars
    assert len(long_content) > 2048
    result = _result(
        await handler.handle(
            command(
                "message.record",
                {
                    "message_id": "msg_long",
                    "session_id": "con_1",
                    "agent_id": "agent_1",
                    "role": "user",
                    "sequence_number": 1,
                    "content": long_content,
                },
            )
        )
    )
    assert result.get("ok", True) is not False
    assert result["recorded"] is True
    stored = await handler._repository.get_message("user_1", "msg_long")
    assert stored is not None
    assert stored.content == long_content[:2048]
    assert stored.content.startswith("long-turn-")
    # the memory record handed to the indexer carries the same bounded content
    indexed_records = handler._indexer.indexed[-1]
    assert indexed_records[0].content == long_content[:2048]


async def test_lookup_truncates_long_query(seeded_handler) -> None:
    """Follow-up A: a >2048-char lookup query is truncated, not validation_error.

    The query keeps the exact 2048-char prefix, the search is consulted with that
    truncated query, and a matching hit is returned so the B2 retrieved-context
    block can appear for long user turns.
    """
    handler = seeded_handler
    handler._searcher.hits = [{"source_id": "msg_1", "text": "match", "score": 0.9}]
    long_query = "Q" * 5000
    assert len(long_query) > 2048
    result = _result(
        await handler.handle(
            command("memory.lookup", {"query": long_query, "sources": ["chat_history"]})
        )
    )
    assert result.get("ok", True) is not False
    assert result["query"] == long_query[:2048]
    assert handler._searcher.calls[-1]["query"] == long_query[:2048]
    assert result["results"]["chat_history"][0]["source_id"] == "msg_1"
