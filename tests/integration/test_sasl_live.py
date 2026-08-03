"""Opt-in live SASL_SSL verification against a throwaway Redpanda container.

Gated on ``RAG_SASL_LIVE=1`` (see ``examples/local/verify-sasl.sh``, which
starts the throwaway ``redpanda-rag-sasl`` container on 127.0.0.1:19093,
bootstraps the SCRAM superuser, and runs this test). Proves the RAG broker
clients connect over SASL_SSL: bootstrap topics, publish one envelope, and
consume it back.
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
from shared.contracts import MessageEnvelope, MessageType, TOPICS

pytestmark = pytest.mark.live_infra

_SASL_PASSWORD = os.environ.get("RAG_SASL_PASSWORD", "verify-sasl-secret")
_SASL_CAFILE = os.environ.get("RAG_SASL_CAFILE", ".run/sasl-certs/ca.crt")


def _require_sasl_live() -> None:
    if os.environ.get("RAG_SASL_LIVE") != "1":
        pytest.skip("set RAG_SASL_LIVE=1 to run SASL live verification")


def _sasl_settings() -> BrokerSettings:
    return BrokerSettings(
        broker_type="redpanda",
        bootstrap_servers="127.0.0.1:19093",
        client_id="sasl-live-verify",
        security_protocol="SASL_SSL",
        sasl_mechanism="SCRAM-SHA-256",
        sasl_plain_username="admin",
        sasl_plain_password=_SASL_PASSWORD,
        ssl_cafile=_SASL_CAFILE,
    )


@pytest.mark.asyncio
async def test_sasl_live_rag_clients_connect() -> None:
    _require_sasl_live()
    settings = _sasl_settings()
    admin = create_redpanda_admin(settings)
    producer = create_redpanda_producer(settings)
    consumer = create_redpanda_consumer(
        settings,
        topic=TOPICS.domain_memory_commands,
        group_id=f"sasl-live-{uuid4().hex}",
    )
    await admin.start()
    try:
        await bootstrap_topics(admin)
        health = await admin.health(required_topics=required_topics())
        assert health.ok is True, health

        envelope = MessageEnvelope.create(
            producer="sasl_live_verify",
            message_type=MessageType.DOMAIN_COMMAND,
            data_type="agent_memory",
            task_id=f"sasl-live-{uuid4().hex}",
            correlation_id=f"corr-sasl-{uuid4().hex}",
            payload={"operation": "session.start", "request": {}},
        )
        await producer.start()
        await producer.publish(TOPICS.domain_memory_commands, envelope, key=envelope.task_id)

        await consumer.start()
        consumed = await asyncio.wait_for(
            consumer.consume(TOPICS.domain_memory_commands), timeout=15
        )
        assert consumed.message_id == envelope.message_id
        assert consumed.payload["operation"] == "session.start"
    finally:
        for component in (consumer, producer):
            try:
                await component.stop()
            except Exception:
                pass
        await admin.stop()
