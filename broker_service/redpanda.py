"""Redpanda/Kafka adapter for shared message envelopes."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from broker_service.config import BrokerSettings
from shared.contracts import MessageEnvelope

logger = logging.getLogger(__name__)


class RedpandaDependencyError(RuntimeError):
    """Raised when the optional Kafka client dependency is not installed."""


class RedpandaConsumeTimeoutError(TimeoutError):
    """Raised when a bounded consume does not receive a message in time."""


@dataclass(frozen=True, slots=True)
class RedpandaHealth:
    ok: bool
    topics: tuple[str, ...] = ()
    error: str = ""

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"ok": self.ok, "topics": list(self.topics)}
        if self.error:
            payload["error"] = self.error
        return payload


def encode_envelope(envelope: MessageEnvelope) -> bytes:
    return json.dumps(envelope.to_mapping(), separators=(",", ":"), sort_keys=True).encode("utf-8")


def decode_envelope(value: bytes | str) -> MessageEnvelope:
    raw = value.decode("utf-8") if isinstance(value, bytes) else value
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("broker message value must be a JSON object")
    return MessageEnvelope.from_mapping(loaded)


@dataclass(slots=True)
class RedpandaProducer:
    settings: BrokerSettings
    _producer: Any | None = None
    _started: bool = False

    def __post_init__(self) -> None:
        if self._producer is None:
            self._producer = _build_kafka_producer(self.settings)

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        configured_topic = self.settings.topic(topic)
        logger.info(
            "broker publish topic=%s task_id=%s message_type=%s producer=%s key=%s",
            configured_topic,
            envelope.task_id,
            envelope.message_type,
            envelope.producer,
            key,
        )
        await self._producer.send_and_wait(
            configured_topic,
            value=encode_envelope(envelope),
            key=key.encode("utf-8") if key else None,
        )

    async def start(self) -> None:
        await self._producer.start()
        self._started = True

    async def stop(self) -> None:
        if self._producer is not None and self._started:
            await self._producer.stop()
            self._started = False


@dataclass(slots=True)
class RedpandaConsumer:
    settings: BrokerSettings
    topic: str
    group_id: str
    _consumer: Any | None = None
    _started: bool = False

    def __post_init__(self) -> None:
        if self._consumer is None:
            self._consumer = _build_kafka_consumer(self.settings, self.topic, self.group_id)

    async def consume(
        self,
        topic: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> MessageEnvelope:
        if topic is not None and self.settings.topic(topic) != self.settings.topic(self.topic):
            raise ValueError("RedpandaConsumer consumes the topic configured at construction")
        if timeout_seconds is None:
            return await self._consume_next()
        try:
            return await asyncio.wait_for(self._consume_next(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise RedpandaConsumeTimeoutError(
                "timed out consuming "
                f"topic={self.settings.topic(self.topic)} group_id={self.group_id}"
            ) from exc

    async def _consume_next(self) -> MessageEnvelope:
        async for message in self._consumer:
            envelope = decode_envelope(message.value)
            logger.info(
                "broker consume topic=%s partition=%s offset=%s group_id=%s task_id=%s message_type=%s producer=%s",
                getattr(message, "topic", self.settings.topic(self.topic)),
                getattr(message, "partition", ""),
                getattr(message, "offset", ""),
                self.group_id,
                envelope.task_id,
                envelope.message_type,
                envelope.producer,
            )
            return envelope
        raise RuntimeError("consumer stopped before receiving a message")

    async def start(self) -> None:
        await self._consumer.start()
        self._started = True

    async def stop(self) -> None:
        if self._consumer is not None and self._started:
            await self._consumer.stop()
            self._started = False

    async def commit(self) -> None:
        if self._consumer is not None and self._started:
            await self._consumer.commit()


@dataclass(slots=True)
class RedpandaAdmin:
    settings: BrokerSettings
    _admin: Any | None = None
    _started: bool = False

    def __post_init__(self) -> None:
        if self._admin is None:
            self._admin = _build_kafka_admin(self.settings)

    async def start(self) -> None:
        start = getattr(self._admin, "start", None)
        if start is not None:
            await start()
        self._started = True

    async def stop(self) -> None:
        if self._admin is None or not self._started:
            return
        close = getattr(self._admin, "close", None)
        if close is not None:
            await close()
            self._started = False
            return
        stop = getattr(self._admin, "stop", None)
        if stop is not None:
            await stop()
        self._started = False

    async def ensure_topics(self, topics: tuple[str, ...], *, partitions: int | None = None) -> None:
        existing = set(await self._admin.list_topics())
        missing = [self.settings.topic(topic) for topic in topics if self.settings.topic(topic) not in existing]
        if not missing:
            return
        await _create_topics(
            self._admin,
            missing,
            partitions=partitions or self.settings.topic_partitions,
        )

    async def health(self, *, required_topics: tuple[str, ...] = ()) -> RedpandaHealth:
        try:
            topics = await self._admin.list_topics()
        except Exception as exc:
            return RedpandaHealth(ok=False, error=str(exc))
        topic_names = tuple(sorted(str(topic) for topic in topics))
        missing = tuple(
            self.settings.topic(topic)
            for topic in required_topics
            if self.settings.topic(topic) not in topic_names
        )
        if missing:
            return RedpandaHealth(
                ok=False,
                topics=topic_names,
                error=f"missing topics: {', '.join(missing)}",
            )
        return RedpandaHealth(ok=True, topics=topic_names)

    async def consumer_group_lag(self, group_id: str, topic: str) -> tuple[int, ...]:
        consumer = _build_lag_consumer(self.settings, group_id)
        await consumer.start()
        try:
            partitions = consumer.partitions_for_topic(topic)
            if not partitions:
                return ()
            topic_partitions = [_topic_partition(topic, partition) for partition in sorted(partitions)]
            end_offsets = await consumer.end_offsets(topic_partitions)
            lags: list[int] = []
            for topic_partition in topic_partitions:
                committed = await consumer.committed(topic_partition)
                end_offset = int(end_offsets.get(topic_partition, 0))
                if committed is None or int(committed) < 0:
                    committed = end_offset
                lags.append(max(0, end_offset - int(committed)))
            return tuple(lags)
        finally:
            await consumer.stop()


def _build_kafka_producer(settings: BrokerSettings) -> Any:
    try:
        from aiokafka import AIOKafkaProducer
    except ImportError as exc:
        raise RedpandaDependencyError(
            "aiokafka is required for the Redpanda runtime adapter"
        ) from exc
    return AIOKafkaProducer(
        bootstrap_servers=settings.bootstrap_servers,
        client_id=settings.client_id,
        request_timeout_ms=int(settings.request_timeout_seconds * 1000),
    )


def _build_kafka_consumer(settings: BrokerSettings, topic: str, group_id: str) -> Any:
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError as exc:
        raise RedpandaDependencyError(
            "aiokafka is required for the Redpanda runtime adapter"
        ) from exc
    return AIOKafkaConsumer(
        settings.topic(topic),
        bootstrap_servers=settings.bootstrap_servers,
        client_id=settings.client_id,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )


def _build_lag_consumer(settings: BrokerSettings, group_id: str) -> Any:
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError as exc:
        raise RedpandaDependencyError(
            "aiokafka is required for the Redpanda runtime adapter"
        ) from exc
    return AIOKafkaConsumer(
        bootstrap_servers=settings.bootstrap_servers,
        client_id=f"{settings.client_id}-lag",
        group_id=group_id,
        enable_auto_commit=False,
        request_timeout_ms=int(settings.request_timeout_seconds * 1000),
    )


def _topic_partition(topic: str, partition: int) -> Any:
    try:
        from aiokafka import TopicPartition
    except ImportError as exc:
        raise RedpandaDependencyError(
            "aiokafka is required for the Redpanda runtime adapter"
        ) from exc
    return TopicPartition(topic, partition)


def _build_kafka_admin(settings: BrokerSettings) -> Any:
    try:
        from aiokafka.admin import AIOKafkaAdminClient
    except ImportError as exc:
        raise RedpandaDependencyError(
            "aiokafka is required for the Redpanda runtime adapter"
        ) from exc
    return AIOKafkaAdminClient(
        bootstrap_servers=settings.bootstrap_servers,
        client_id=settings.client_id,
        request_timeout_ms=int(settings.request_timeout_seconds * 1000),
    )


async def _create_topics(admin: Any, topic_names: list[str], *, partitions: int) -> None:
    try:
        from aiokafka.admin import NewTopic
    except ImportError:
        await admin.create_topics(topic_names, partitions=partitions)
        return
    topics = [
        NewTopic(name=name, num_partitions=partitions, replication_factor=1)
        for name in topic_names
    ]
    await admin.create_topics(topics)
