"""Shared fixtures for memory_service tests.

Builds a ``MemoryDomainHandler`` over the in-memory repository with fake
indexer/searcher/identity sources, and mints real service tokens over the same
HS256 code path the local/fake mode uses (requirements §8). Envelope helpers
produce correctly-shaped DOMAIN_COMMANDs for each of the 8 operations.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from memory_service.compression import CondenseV1Policy
from memory_service.domain_handler import MemoryDomainHandler
from memory_service.identity import FakeIdentitySource
from memory_service.indexer import FakeMemoryIndexer
from memory_service.repository import MemoryInMemoryRepository
from memory_service.searcher import FakeMemorySearcher
from shared.contracts import MessageEnvelope, MessageType
from shared.service_auth import ServiceAuthSettings, create_service_token

SIGNING_KEY = "local-dev-signing-key"
ISSUER = "simple-agent-local"
AUDIENCE = "simple-agent-internal"


@pytest.fixture
def auth_settings() -> ServiceAuthSettings:
    return ServiceAuthSettings(
        signing_key=SIGNING_KEY,
        issuer=ISSUER,
        audience=AUDIENCE,
        allowed_services=("conversation-server",),
    )


@pytest.fixture
def handler(auth_settings: ServiceAuthSettings) -> MemoryDomainHandler:
    repository = MemoryInMemoryRepository()
    identity = FakeIdentitySource(repository)
    return MemoryDomainHandler(
        repository=repository,
        compression=CondenseV1Policy(),
        indexer=FakeMemoryIndexer(),
        searcher=FakeMemorySearcher(),
        identity_source=identity,
        producer=None,
        service_auth=auth_settings,
    )


@pytest.fixture
async def seeded_handler(handler: MemoryDomainHandler) -> MemoryDomainHandler:
    await handler._identity_source.seed()
    return handler


def token(
    *,
    service: str = "conversation-server",
    actor_user_id: str = "user_1",
    actor_role: str = "tier_1",
    signing_key: str = SIGNING_KEY,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
) -> str:
    return create_service_token(
        settings=ServiceAuthSettings(
            signing_key=signing_key,
            issuer=issuer,
            audience=audience,
        ),
        service=service,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
    )


def command(
    operation: str,
    request: dict[str, Any] | None = None,
    *,
    actor_user_id: str = "user_1",
    agent_id: str = "agent_1",
    headers: dict[str, str] | None = None,
    correlation_id: str = "corr-1",
    task_id: str = "task-1",
    context: dict[str, Any] | None = None,
) -> MessageEnvelope:
    base_headers = {
        "X-Service-Name": "conversation-server",
        "Authorization": f"Bearer {token(actor_user_id=actor_user_id)}",
        "X-Actor-User-ID": actor_user_id,
        "X-Actor-Role": "tier_1",
        "X-Agent-ID": agent_id,
        "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
    }
    if headers:
        base_headers.update(headers)
    payload: dict[str, Any] = {"operation": operation}
    if request is not None:
        payload["request"] = request
    if context:
        payload["context"] = context
    return MessageEnvelope.create(
        producer="conversation-server",
        message_type=MessageType.DOMAIN_COMMAND,
        data_type="agent_memory",
        task_id=task_id,
        correlation_id=correlation_id,
        headers=base_headers,
        payload=payload,
    )


def request_hash(request: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
