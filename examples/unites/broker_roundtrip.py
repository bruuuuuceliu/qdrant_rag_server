"""Live Redpanda broker round-trip showcase.

Setup:
1. Install dependencies: ``python -m pip install -e .``
2. Start Redpanda locally or run ``examples/local/run-all.sh --init``.
3. Optional: set ``BROKER_BOOTSTRAP_SERVERS`` in ``examples/unites/.env``.
4. Run: ``python -m examples.unites.broker_roundtrip``

This showcase uses the same Redpanda producer, consumer, admin, topic bootstrap,
and message-envelope contract used by broker-first runtime services.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from broker_service import (  # noqa: E402
    BrokerSettings,
    RedpandaConsumeTimeoutError,
    bootstrap_topics,
    create_redpanda_admin,
    create_redpanda_consumer,
    create_redpanda_producer,
    required_topics,
)
from shared.contracts import MessageEnvelope, MessageType, TOPICS  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"))


def build_showcase_settings(values: dict[str, str] | None = None) -> BrokerSettings:
    values = dict(values or os.environ)
    base = BrokerSettings.from_values(values)
    topic_prefix = values.get("BROKER_TOPIC_PREFIX") or f"unite.{uuid4().hex}."
    return BrokerSettings(
        broker_type=base.broker_type,
        bootstrap_servers=base.bootstrap_servers,
        client_id=f"{base.client_id}-unite-broker",
        request_timeout_seconds=base.request_timeout_seconds,
        topic_prefix=topic_prefix,
        topic_partitions=base.topic_partitions,
    )


def build_showcase_envelope() -> MessageEnvelope:
    return MessageEnvelope.create(
        producer="examples.unites.broker_roundtrip",
        message_type=MessageType.TASK_STEP,
        data_type="broker_showcase",
        payload={
            "operation": "roundtrip",
            "message": "hello from broker_roundtrip",
        },
    )


async def main() -> None:
    settings = build_showcase_settings()
    admin = create_redpanda_admin(settings)
    producer = create_redpanda_producer(settings)
    consumer = create_redpanda_consumer(
        settings,
        topic=TOPICS.task_step_events,
        group_id=f"unite-broker-{uuid4().hex}",
    )
    producer_started = False
    consumer_started = False

    print(f"Using Redpanda bootstrap_servers={settings.bootstrap_servers}")
    print(f"Using topic_prefix={settings.topic_prefix!r}")

    try:
        await admin.start()
        await bootstrap_topics(admin, settings=settings)
        health = await admin.health(required_topics=required_topics())
        if not health.ok:
            raise RuntimeError(f"broker health failed: {health.to_payload()}")

        await producer.start()
        producer_started = True
        await consumer.start()
        consumer_started = True

        envelope = build_showcase_envelope()
        await producer.publish(TOPICS.task_step_events, envelope, key=envelope.task_id)
        received = await consumer.consume(
            TOPICS.task_step_events,
            timeout_seconds=float(os.getenv("BROKER_SHOWCASE_TIMEOUT_SECONDS", "15")),
        )

        print("Published and consumed one broker envelope")
        print(f"topic={settings.topic(TOPICS.task_step_events)}")
        print(f"message_id={received.message_id}")
        print(f"task_id={received.task_id}")
        print(f"payload={received.payload}")
    except RedpandaConsumeTimeoutError as exc:
        print(f"Timed out waiting for broker message: {exc}")
        raise SystemExit(1) from exc
    finally:
        if consumer_started:
            await consumer.stop()
        if producer_started:
            await producer.stop()
        await admin.stop()


if __name__ == "__main__":
    asyncio.run(main())
