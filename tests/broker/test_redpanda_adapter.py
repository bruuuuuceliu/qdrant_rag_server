"""Redpanda broker adapter tests."""

from __future__ import annotations

import asyncio

import pytest
from importlib.util import find_spec

from broker_service.config import BrokerSettings
from broker_service.redpanda import (
    RedpandaAdmin,
    RedpandaConsumer,
    RedpandaConsumeTimeoutError,
    RedpandaDependencyError,
    RedpandaProducer,
    decode_envelope,
    encode_envelope,
)
from shared.contracts import MessageEnvelope, MessageType, TOPICS


class FakeKafkaProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes, bytes | None]] = []
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(self, topic: str, *, value: bytes, key: bytes | None = None) -> None:
        self.sent.append((topic, value, key))


class FakeKafkaMessage:
    def __init__(self, value: bytes) -> None:
        self.value = value


class FakeKafkaConsumer:
    def __init__(self, messages: list[FakeKafkaMessage]) -> None:
        self.messages = messages
        self.started = False
        self.stopped = False
        self.committed = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def commit(self) -> None:
        self.committed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)


class HangingKafkaConsumer(FakeKafkaConsumer):
    async def __anext__(self):
        await asyncio.sleep(60)
        raise StopAsyncIteration


class FakeKafkaAdmin:
    def __init__(self, topics: set[str] | None = None, *, fail: bool = False) -> None:
        self.topics = topics or set()
        self.created: list[tuple[str, int]] = []
        self.fail = fail
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def list_topics(self) -> set[str]:
        if self.fail:
            raise RuntimeError("broker down")
        return set(self.topics)

    async def create_topics(self, topics: list[str], *, partitions: int) -> None:
        for topic in topics:
            self.created.append((topic, partitions))
            self.topics.add(topic)


class FakeAioKafkaAdmin(FakeKafkaAdmin):
    async def create_topics(self, topics) -> None:
        for topic in topics:
            self.created.append((topic.name, topic.num_partitions))
            self.topics.add(topic.name)


@pytest.mark.parametrize("broker_type", ("redpanda", "kafka"))
def test_broker_settings_loads_from_values_and_prefixes_topics(broker_type: str) -> None:
    settings = BrokerSettings.from_values(
        {
            "BROKER_TYPE": broker_type,
            "BROKER_BOOTSTRAP_SERVERS": "redpanda:9092",
            "BROKER_CLIENT_ID": "tests",
            "BROKER_REQUEST_TIMEOUT_SECONDS": "12.5",
            "BROKER_TOPIC_PREFIX": "local.",
        }
    )

    assert settings.bootstrap_servers == "redpanda:9092"
    assert settings.broker_type == broker_type
    assert settings.client_id == "tests"
    assert settings.request_timeout_seconds == 12.5
    assert settings.topic(TOPICS.task_intake) == "local.task.intake"


@pytest.mark.parametrize(
    ("values", "match"),
    (
        ({"BROKER_TYPE": "rabbitmq"}, "BROKER_TYPE"),
        ({"BROKER_BOOTSTRAP_SERVERS": " "}, "BROKER_BOOTSTRAP_SERVERS"),
        ({"BROKER_CLIENT_ID": ""}, "BROKER_CLIENT_ID"),
        ({"BROKER_REQUEST_TIMEOUT_SECONDS": "0"}, "BROKER_REQUEST_TIMEOUT_SECONDS"),
        ({"BROKER_TOPIC_PARTITIONS": "0"}, "BROKER_TOPIC_PARTITIONS"),
        ({"BROKER_TOPIC_PREFIX": "bad prefix."}, "BROKER_TOPIC_PREFIX"),
    ),
)
def test_broker_settings_rejects_invalid_values(values: dict[str, str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        BrokerSettings.from_values(values)


def test_encode_decode_envelope_round_trip() -> None:
    envelope = MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
        payload={"operation": "ingest"},
    )

    decoded = decode_envelope(encode_envelope(envelope))

    assert decoded == envelope


@pytest.mark.asyncio
async def test_redpanda_producer_uses_injected_client() -> None:
    fake = FakeKafkaProducer()
    settings = BrokerSettings(topic_prefix="dev.")
    producer = RedpandaProducer(settings=settings, _producer=fake)
    envelope = MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
    )

    await producer.start()
    await producer.publish(TOPICS.task_intake, envelope, key="task-1")
    await producer.stop()

    assert fake.started is True
    assert fake.stopped is True
    assert fake.sent[0][0] == "dev.task.intake"
    assert fake.sent[0][2] == b"task-1"
    assert decode_envelope(fake.sent[0][1]) == envelope


@pytest.mark.asyncio
async def test_redpanda_consumer_uses_configured_topic_and_decodes_envelope() -> None:
    envelope = MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
    )
    fake = FakeKafkaConsumer([FakeKafkaMessage(encode_envelope(envelope))])
    consumer = RedpandaConsumer(
        settings=BrokerSettings(topic_prefix="dev."),
        topic=TOPICS.task_intake,
        group_id="task-manager",
        _consumer=fake,
    )

    await consumer.start()
    consumed = await consumer.consume(TOPICS.task_intake)
    await consumer.commit()
    await consumer.stop()

    assert consumed == envelope
    assert fake.started is True
    assert fake.committed is True
    assert fake.stopped is True
    with pytest.raises(ValueError, match="configured"):
        await consumer.consume(TOPICS.task_results)


@pytest.mark.asyncio
async def test_redpanda_consumer_bounded_consume_returns_message() -> None:
    envelope = MessageEnvelope.create(
        producer="manager_service",
        message_type=MessageType.REQUEST_ACCEPTED,
        data_type="project_document",
        task_id="task-1",
        correlation_id="corr-1",
    )
    consumer = RedpandaConsumer(
        settings=BrokerSettings(topic_prefix="dev."),
        topic=TOPICS.task_intake,
        group_id="task-manager",
        _consumer=FakeKafkaConsumer([FakeKafkaMessage(encode_envelope(envelope))]),
    )

    consumed = await consumer.consume(TOPICS.task_intake, timeout_seconds=1)

    assert consumed == envelope


@pytest.mark.asyncio
async def test_redpanda_consumer_bounded_consume_times_out_with_context() -> None:
    consumer = RedpandaConsumer(
        settings=BrokerSettings(topic_prefix="dev."),
        topic=TOPICS.task_intake,
        group_id="task-manager",
        _consumer=HangingKafkaConsumer([]),
    )

    with pytest.raises(RedpandaConsumeTimeoutError, match="dev.task.intake.*task-manager"):
        await consumer.consume(TOPICS.task_intake, timeout_seconds=0.01)


@pytest.mark.asyncio
async def test_redpanda_lifecycle_stop_tolerates_never_started_clients() -> None:
    producer = RedpandaProducer(settings=BrokerSettings(), _producer=FakeKafkaProducer())
    consumer = RedpandaConsumer(
        settings=BrokerSettings(),
        topic=TOPICS.task_intake,
        group_id="task-manager",
        _consumer=FakeKafkaConsumer([]),
    )
    admin = RedpandaAdmin(settings=BrokerSettings(), _admin=FakeKafkaAdmin())

    await producer.stop()
    await consumer.stop()
    await admin.stop()


def test_redpanda_producer_reports_missing_optional_dependency() -> None:
    if find_spec("aiokafka") is not None:
        pytest.skip("aiokafka is installed in this environment")
    with pytest.raises(RedpandaDependencyError, match="aiokafka"):
        RedpandaProducer(settings=BrokerSettings())


@pytest.mark.asyncio
async def test_redpanda_admin_creates_missing_prefixed_topics() -> None:
    fake = FakeAioKafkaAdmin(topics={"dev.task.intake"})
    admin = RedpandaAdmin(settings=BrokerSettings(topic_prefix="dev."), _admin=fake)

    await admin.ensure_topics((TOPICS.task_intake, TOPICS.task_results), partitions=3)

    assert fake.created == [("dev.task.results", 3)]


@pytest.mark.asyncio
async def test_redpanda_admin_lifecycle_uses_injected_client() -> None:
    fake = FakeKafkaAdmin()
    admin = RedpandaAdmin(settings=BrokerSettings(), _admin=fake)

    await admin.start()
    await admin.stop()

    assert fake.started is True
    assert fake.closed is True


@pytest.mark.asyncio
async def test_redpanda_admin_health_reports_topics_and_errors() -> None:
    healthy = RedpandaAdmin(settings=BrokerSettings(), _admin=FakeKafkaAdmin(topics={"b", "a"}))
    unhealthy = RedpandaAdmin(settings=BrokerSettings(), _admin=FakeKafkaAdmin(fail=True))

    assert (await healthy.health()).to_payload() == {"ok": True, "topics": ["a", "b"]}
    assert (await unhealthy.health()).ok is False


@pytest.mark.asyncio
async def test_redpanda_admin_health_checks_required_topics() -> None:
    admin = RedpandaAdmin(settings=BrokerSettings(topic_prefix="dev."), _admin=FakeKafkaAdmin(topics={"dev.a"}))

    health = await admin.health(required_topics=("a", "b"))

    assert health.ok is False
    assert "dev.b" in health.error
