"""Broker runtime factory helpers."""

from __future__ import annotations

from broker_service.config import BrokerSettings
from broker_service.message_bus import BrokerMessageBus
from broker_service.redpanda import RedpandaAdmin, RedpandaConsumer, RedpandaProducer


def create_redpanda_producer(settings: BrokerSettings) -> RedpandaProducer:
    return RedpandaProducer(settings=settings)


def create_redpanda_consumer(
    settings: BrokerSettings,
    *,
    topic: str,
    group_id: str,
) -> RedpandaConsumer:
    return RedpandaConsumer(settings=settings, topic=topic, group_id=group_id)


def create_redpanda_admin(settings: BrokerSettings) -> RedpandaAdmin:
    return RedpandaAdmin(settings=settings)


def create_redpanda_bus(
    settings: BrokerSettings,
    *,
    topic: str | None = None,
    group_id: str | None = None,
) -> BrokerMessageBus:
    producer = create_redpanda_producer(settings)
    consumer = None
    if topic is not None:
        if not group_id:
            raise ValueError("group_id is required when topic is provided")
        consumer = create_redpanda_consumer(settings, topic=topic, group_id=group_id)
    return BrokerMessageBus(producer=producer, consumer=consumer, consumer_topic=topic or "")
