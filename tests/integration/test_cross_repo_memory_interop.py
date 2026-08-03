"""Cross-repo memory integration: simple_agent caller ↔ RAG memory_service.

Proves real interop between the two repos without a broker:
1. A service token minted by simple_agent's ``simple_agent_service_auth``
   verifies in the RAG repo's ``shared/service_auth`` mirror (same HS256
   algorithm, header, claims, and local-dev defaults).
2. A DOMAIN_COMMAND envelope shaped exactly as ``MemoryBrokerClient`` builds it
   (operation ``memory.compress``, headers per requirements §7.1) is accepted
   and answered by the RAG ``MemoryDomainHandler``.

The simple_agent lib is imported from its own checkout via sys.path, so this
test asserts the contract, not a copy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SIMPLE_AGENT_AUTH_SRC = ROOT / "../simple_agent/libs/service-auth/src"
SIMPLE_AGENT_AUTH_SRC = SIMPLE_AGENT_AUTH_SRC.resolve()
if str(SIMPLE_AGENT_AUTH_SRC) not in sys.path:
    sys.path.insert(0, str(SIMPLE_AGENT_AUTH_SRC))

from memory_service.compression import CondenseV1Policy
from memory_service.domain_handler import MemoryDomainHandler
from memory_service.identity import FakeIdentitySource
from memory_service.indexer import FakeMemoryIndexer
from memory_service.repository import MemoryInMemoryRepository
from memory_service.searcher import FakeMemorySearcher
from shared.contracts import MessageEnvelope, MessageType
from shared.service_auth import ServiceAuthSettings as RagServiceAuthSettings
from shared.service_auth import verify_service_token
from simple_agent_service_auth import (
    ServiceAuthSettings as SaServiceAuthSettings,
    create_service_token,
)


def test_simple_agent_token_verifies_in_rag_service_auth() -> None:
    # Mint with simple_agent's lib using the local-dev defaults (what the
    # broker client does when env is unset).
    sa_settings = SaServiceAuthSettings(
        signing_key="local-dev-signing-key",
        issuer="simple-agent-local",
        audience="simple-agent-internal",
        allowed_services=("gateway-server", "conversation-server"),
    )
    token = create_service_token(
        settings=sa_settings,
        service="conversation-server",
        actor_user_id="user_1",
        actor_role="tier_1",
    )

    claims = verify_service_token(
        token,
        settings=RagServiceAuthSettings(
            signing_key="local-dev-signing-key",
            issuer="simple-agent-local",
            audience="simple-agent-internal",
            allowed_services=("conversation-server",),
        ),
    )
    assert claims.service == "conversation-server"
    assert claims.actor_user_id == "user_1"
    assert claims.actor_role == "tier_1"


async def _memory_handler() -> MemoryDomainHandler:
    repository = MemoryInMemoryRepository()
    return MemoryDomainHandler(
        repository=repository,
        compression=CondenseV1Policy(),
        indexer=FakeMemoryIndexer(),
        searcher=FakeMemorySearcher(),
        identity_source=FakeIdentitySource(repository),
        producer=None,
        service_auth=RagServiceAuthSettings(
            allowed_services=("conversation-server",),
        ),
    )


async def test_broker_client_shaped_envelope_processes_through_handler() -> None:
    handler = await _memory_handler()
    await handler._identity_source.seed()

    # Session + two messages, exactly as MemoryBrokerClient would record them
    for envelope in (
        _client_command(
            "session.start",
            {"session_id": "con_x", "agent_id": "agent_1"},
            publish_agent="agent_1",
        ),
        _client_command(
            "message.record",
            {
                "message_id": "msg_x1",
                "session_id": "con_x",
                "agent_id": "agent_1",
                "role": "user",
                "sequence_number": 1,
                "content": "user mentioned a dietary preference for gluten-free",
            },
            publish_agent="agent_1",
        ),
        _client_command(
            "message.record",
            {
                "message_id": "msg_x2",
                "session_id": "con_x",
                "agent_id": "agent_1",
                "role": "assistant",
                "sequence_number": 2,
                "content": "noted, gluten-free preference recorded",
            },
            publish_agent="agent_1",
        ),
    ):
        reply = await handler.handle(envelope)
        assert reply.message_type == MessageType.DOMAIN_RESULT

    # compress — a request/reply op, exactly as the saga's _best_effort_call does
    compress_envelope = _client_command(
        "memory.compress",
        {
            "session_id": "con_x",
            "start_sequence": 1,
            "end_sequence": 2,
            "keep_recent": 0,
            "policy": "condense-v1",
            "idempotency_key": "compress:con_x:1:2:0:condense-v1",
        },
        publish_agent="agent_1",
    )
    reply = await handler.handle(compress_envelope)
    assert reply.message_type == MessageType.DOMAIN_RESULT
    result = reply.payload["result"]
    assert "ok" not in result, f"success result should not be an error: {result}"
    assert result["condensed_context"]
    assert result["memory_id"].startswith("mem_sum_")
    assert result["covered_range"] == {"from": 1, "to": 2}

    # profile.read (user-scoped: X-Agent-ID present but not payload-compared)
    profile_envelope = _client_command(
        "profile.read",
        {"include_inactive_facts": False},
        publish_agent="agent_1",
    )
    profile_reply = await handler.handle(profile_envelope)
    assert profile_reply.payload["result"]["profile"]["user_id"] == "user_1"


def _client_command(
    operation: str,
    request: dict[str, object],
    *,
    publish_agent: str,
) -> MessageEnvelope:
    """Build the envelope exactly as ``MemoryBrokerClient._build_envelope`` does."""
    sa_settings = SaServiceAuthSettings(
        signing_key="local-dev-signing-key",
        issuer="simple-agent-local",
        audience="simple-agent-internal",
        allowed_services=("gateway-server", "conversation-server"),
    )
    token = create_service_token(
        settings=sa_settings,
        service="conversation-server",
        actor_user_id="user_1",
        actor_role="tier_1",
    )
    return MessageEnvelope.create(
        message_id="msg_mem_x",
        correlation_id="corr_x",
        task_id="task_x",
        producer="conversation-server",
        message_type=MessageType.DOMAIN_COMMAND,
        data_type="agent_memory",
        schema_version="1",
        created_at="2026-08-02T00:00:00Z",
        headers={
            "X-Service-Name": "conversation-server",
            "Authorization": f"Bearer {token}",
            "X-Actor-User-ID": "user_1",
            "X-Actor-Role": "tier_1",
            "X-Agent-ID": publish_agent,
            "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
        },
        payload={
            "operation": operation,
            "request": request,
            "context": {
                "request_id": "req_x",
                "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
                "response_topic": "domain.memory.results",
            },
        },
    )
