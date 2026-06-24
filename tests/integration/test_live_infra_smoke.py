"""Opt-in live Redpanda and Redis infrastructure smoke tests."""

from __future__ import annotations

import os
import asyncio
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
from manager_service.service import ManagerService
from redis_status_node import RedisStatusSettings, RedisTaskStatusStore
from shared.contracts import MessageEnvelope, MessageType, TOPICS, TaskStatusRecord


pytestmark = pytest.mark.live_infra


def _require_live_infra() -> None:
    if os.environ.get("RAG_LIVE_INFRA") != "1":
        pytest.skip("set RAG_LIVE_INFRA=1 to run live infrastructure smoke tests")


@pytest.mark.asyncio
async def test_live_redpanda_bootstrap_publish_and_consume() -> None:
    _require_live_infra()
    settings = BrokerSettings.from_values(dict(os.environ))
    topic_prefix = f"live.{uuid4().hex}."
    settings = BrokerSettings(
        broker_type=settings.broker_type,
        bootstrap_servers=settings.bootstrap_servers,
        client_id=f"{settings.client_id}-smoke",
        request_timeout_seconds=settings.request_timeout_seconds,
        topic_prefix=topic_prefix,
        topic_partitions=settings.topic_partitions,
    )
    admin = create_redpanda_admin(settings)
    producer = create_redpanda_producer(settings)
    consumer = create_redpanda_consumer(
        settings,
        topic=TOPICS.task_intake,
        group_id=f"smoke-{uuid4().hex}",
    )
    producer_started = False
    consumer_started = False
    await admin.start()
    try:
        await bootstrap_topics(admin)
        health = await admin.health(required_topics=required_topics())
        assert health.ok is True
        await producer.start()
        producer_started = True
        await consumer.start()
        consumer_started = True
        envelope = MessageEnvelope.create(
            producer="live_smoke",
            message_type=MessageType.REQUEST_ACCEPTED,
            data_type="project_document",
            payload={"operation": "search", "request": {}, "context": {}},
        )

        await producer.publish(TOPICS.task_intake, envelope, key=envelope.task_id)
        received = await asyncio.wait_for(consumer.consume(TOPICS.task_intake), timeout=15)

        assert received.message_id == envelope.message_id
        assert received.task_id == envelope.task_id
    finally:
        if consumer_started:
            await consumer.stop()
        if producer_started:
            await producer.stop()
        await admin.stop()


@pytest.mark.asyncio
async def test_live_redis_status_ttl_round_trip() -> None:
    _require_live_infra()
    settings = RedisStatusSettings.from_values(dict(os.environ))
    settings = RedisStatusSettings(
        url=settings.url,
        key_prefix=f"live:{uuid4().hex}:",
        completed_ttl_seconds=2,
    )
    store = RedisTaskStatusStore(settings=settings)
    record = TaskStatusRecord(task_id="task-1", status="completed")
    try:
        assert await store.ping() is True
        await store.set_status(record, ttl_seconds=settings.completed_ttl_seconds)

        loaded = await store.get_status("task-1")
        ttl = await store.ttl("task-1")

        assert loaded == record
        assert 0 < ttl <= settings.completed_ttl_seconds
    finally:
        await store.client.aclose()


@pytest.mark.asyncio
async def test_live_manager_publishes_task_intake_and_reads_redis_status() -> None:
    _require_live_infra()
    broker_settings = BrokerSettings.from_values(dict(os.environ))
    topic_prefix = f"manager.{uuid4().hex}."
    broker_settings = BrokerSettings(
        broker_type=broker_settings.broker_type,
        bootstrap_servers=broker_settings.bootstrap_servers,
        client_id=f"{broker_settings.client_id}-manager-smoke",
        request_timeout_seconds=broker_settings.request_timeout_seconds,
        topic_prefix=topic_prefix,
        topic_partitions=broker_settings.topic_partitions,
    )
    redis_settings = RedisStatusSettings.from_values(dict(os.environ))
    redis_settings = RedisStatusSettings(
        url=redis_settings.url,
        key_prefix=f"manager:{uuid4().hex}:",
        completed_ttl_seconds=30,
    )
    admin = create_redpanda_admin(broker_settings)
    producer = create_redpanda_producer(broker_settings)
    consumer = create_redpanda_consumer(
        broker_settings,
        topic=TOPICS.task_intake,
        group_id=f"manager-smoke-{uuid4().hex}",
    )
    status_store = RedisTaskStatusStore(settings=redis_settings)
    manager = ManagerService(task_producer=producer, task_status_store=status_store)
    producer_started = False
    consumer_started = False
    await admin.start()
    try:
        await bootstrap_topics(admin)
        health = await admin.health(required_topics=required_topics())
        assert health.ok is True
        await producer.start()
        producer_started = True
        await consumer.start()
        consumer_started = True
        accepted = await manager.search(
            {
                "task_id": "manager-live-task",
                "project_id": "p1",
                "user_id": "u1",
                "metadata": {"data_type": "project_document"},
            }
        )
        received = await asyncio.wait_for(consumer.consume(TOPICS.task_intake), timeout=15)

        assert accepted.task_id == "manager-live-task"
        assert received.task_id == accepted.task_id
        assert received.producer == "manager_service"
        assert received.payload["operation"] == "search"
        assert received.payload["request"]["project_id"] == "p1"

        record = TaskStatusRecord(task_id=accepted.task_id, status="completed")
        await status_store.set_status(record, ttl_seconds=redis_settings.completed_ttl_seconds)
        assert await manager.ingest_status(accepted.task_id) == record
    finally:
        if consumer_started:
            await consumer.stop()
        if producer_started:
            await producer.stop()
        await admin.stop()
        await status_store.client.aclose()
