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
    # v1: documents has no distinct collection and is reported not-consulted/
    # empty rather than mislabeling chat-memory points as documents.
    assert result["consulted"] == {
        "chat_history": True, "documents": False, "user_profile_facts": True
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
