"""Opt-in live Redpanda memory round-trip test.

Proves the memory command path end-to-end over a real broker without needing
the memory worker or the retrieval worker to be running:

1. The memory topics (``domain.memory.commands`` / ``domain.memory.results``)
   are bootstrapped alongside the canonical topic set.
2. A ``session.start`` DOMAIN_COMMAND published to ``domain.memory.commands``
   is consumable from that topic.
3. The in-process ``MemoryDomainHandler`` answers it and publishes the
   DOMAIN_RESULT to ``domain.memory.results`` (the same topic the worker would
   use), which a second consumer reads back.

The handler uses fake indexer/searcher/identity ports (no retrieval/Qdrant
dependency) and a real broker producer so the result actually lands on the
broker.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from broker_service import (
    BrokerSettings,
    bootstrap_topics,
    create_redpanda_admin,
    create_redpanda_consumer,
    create_redpanda_producer,
    required_topics,
)
from memory_service.compression import CondenseV1Policy
from memory_service.domain_handler import MemoryDomainHandler
from memory_service.identity import FakeIdentitySource
from memory_service.indexer import FakeMemoryIndexer
from memory_service.repository import MemoryInMemoryRepository
from memory_service.searcher import FakeMemorySearcher
from shared.contracts import TOPICS, MessageType
from shared.service_auth import ServiceAuthSettings
from tests.memory.conftest import command

pytestmark = pytest.mark.live_infra


def _require_live_infra() -> None:
    if os.environ.get("RAG_LIVE_INFRA") != "1":
        pytest.skip("set RAG_LIVE_INFRA=1 to run live infrastructure memory tests")


def _live_broker_settings() -> BrokerSettings:
    base = BrokerSettings.from_values(dict(os.environ))
    return BrokerSettings(
        broker_type=base.broker_type,
        bootstrap_servers=base.bootstrap_servers,
        client_id=f"{base.client_id}-mem-live",
        request_timeout_seconds=base.request_timeout_seconds,
        topic_prefix=f"live.{uuid4().hex}.",
        topic_partitions=base.topic_partitions,
    )


@pytest.mark.asyncio
async def test_live_memory_session_command_roundtrip_via_broker() -> None:
    _require_live_infra()
    broker_settings = _live_broker_settings()
    admin = create_redpanda_admin(broker_settings)
    producer = create_redpanda_producer(broker_settings)
    command_consumer = create_redpanda_consumer(
        broker_settings,
        topic=TOPICS.domain_memory_commands,
        group_id=f"mem-live-cmd-{uuid4().hex}",
    )
    result_consumer = create_redpanda_consumer(
        broker_settings,
        topic=TOPICS.domain_memory_results,
        group_id=f"mem-live-res-{uuid4().hex}",
    )
    await admin.start()
    try:
        await bootstrap_topics(admin)
        health = await admin.health(required_topics=required_topics())
        assert health.ok is True
        await producer.start()
        await command_consumer.start()
        await result_consumer.start()

        repository = MemoryInMemoryRepository()
        await repository.initialize()
        handler = MemoryDomainHandler(
            repository=repository,
            compression=CondenseV1Policy(),
            indexer=FakeMemoryIndexer(),
            searcher=FakeMemorySearcher(),
            identity_source=FakeIdentitySource(repository),
            producer=producer,
            service_auth=ServiceAuthSettings(
                signing_key="local-dev-signing-key",
                issuer="simple-agent-local",
                audience="simple-agent-internal",
                allowed_services=("conversation-server",),
            ),
            result_topic=TOPICS.domain_memory_results,
        )

        envelope = command(
            "session.start",
            {"session_id": "live_session_1", "agent_id": "agent_1"},
            correlation_id="live-mem-corr",
            task_id="live-mem-task",
        )
        await producer.publish(
            TOPICS.domain_memory_commands, envelope, key=envelope.task_id
        )

        consumed_command = await asyncio.wait_for(
            command_consumer.consume(TOPICS.domain_memory_commands), timeout=15
        )
        assert consumed_command.message_id == envelope.message_id
        assert consumed_command.message_type == MessageType.DOMAIN_COMMAND
        assert consumed_command.payload["operation"] == "session.start"

        reply = await handler.handle(consumed_command)
        assert reply.message_type == MessageType.DOMAIN_RESULT
        assert reply.payload["operation"] == "session.start"

        published_result = await asyncio.wait_for(
            result_consumer.consume(TOPICS.domain_memory_results), timeout=15
        )
        assert published_result.message_type == MessageType.DOMAIN_RESULT
        assert published_result.payload["operation"] == "session.start"
        result = published_result.payload["result"]
        assert result["created"] is True
        assert result["session"]["session_id"] == "live_session_1"
    finally:
        for component in (command_consumer, result_consumer, producer):
            try:
                await component.stop()
            except Exception:
                pass
        await admin.stop()
