"""Redpanda broker adapter tests."""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path

import pytest
from importlib.util import find_spec

from broker_service.config import BrokerSettings
from broker_service.redpanda import (
    RedpandaAdmin,
    RedpandaConsumer,
    RedpandaConsumeTimeoutError,
    RedpandaDependencyError,
    RedpandaProducer,
    _build_kafka_admin,
    _build_kafka_consumer,
    _build_lag_consumer,
    _build_kafka_producer,
    _kafka_security_kwargs,
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


# ---------------------------------------------------------------------------
# C5: broker SASL/TLS security kwargs
# ---------------------------------------------------------------------------

# A valid self-signed CA certificate so ``ssl.create_default_context(cafile=...)``
# can parse the file (it rejects arbitrary text).
_VALID_CA_PEM = """\
-----BEGIN CERTIFICATE-----
MIIDBTCCAe2gAwIBAgIUH4J7A8A7L2IVl6hPvlr0RS2EIWcwDQYJKoZIhvcNAQEL
BQAwEjEQMA4GA1UEAwwHdGVzdC1jYTAeFw0yNjA4MDMxNTQxNDBaFw0zNjA3MzEx
NTQxNDBaMBIxEDAOBgNVBAMMB3Rlc3QtY2EwggEiMA0GCSqGSIb3DQEBAQUAA4IB
DwAwggEKAoIBAQCr4UzuzKnuKUBSFCzmwIP/11CGeW2pUdeLFJ83ZAMCb7aZEkeg
Kis8/gdJg92hHaysdlAChSS93Irn0c0yusrzAb10Ma7v41bzow0ix02QT9ssjBdY
Im1yogkqnOdgEMO2zEjysnEGVkDj2bSmDeL6dNHbD6+qeiHHDvtIawypVJo0wYKF
7sjXXCZB7XBOrUUVF7aSqVLzbZFsQx6R2Nsg4LQnAFV/dWneworKjqdY5FYLISQY
+U2SKwhBs0bPm1usBK7bxMofC21NsrThytZgwQf43StTRL3Cy6Rt7zgTJF0myrp1
pHIyuQRnjob2+vQfui2w92vyfOLT0IOOktefAgMBAAGjUzBRMB0GA1UdDgQWBBSr
UA2ttXYEeNVx+ypXa6CvxXKICTAfBgNVHSMEGDAWgBSrUA2ttXYEeNVx+ypXa6Cv
xXKICTAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3DQEBCwUAA4IBAQAzgnzfvvVz
HUMfB5BdYyV7It1NZmTvtnMkxBUWyDMNYpLNsnNueSFs3glpJKpQL4EemDp0RWA3
kuNOuB+E2FTEbcdOMf93d8+TnCHRAgkygKBIdbJxvhEOPPRoVt3VDjCj5su36QOf
sHmORgPK1O6Wu7GMirA+eUqHHR8WxSUNQkxpYATGjzCjGVkKO7ESYfI/e8jDr4KG
Biwrz5om0sOIET014ORhfxB5VNFeQtk4gN15+8Yksyx4VWDyPqVKovraAjkC1atI
Qaxh+vqN/fF5Q56NLdZb5pjMiZ+hWfRkXZofgoYwg+D3EMCDVrMyK2nDEipJiAuj
reYbX7DnLevR
-----END CERTIFICATE-----
"""

_VALID_CLIENT_CERT_PEM = """\
-----BEGIN CERTIFICATE-----
MIIDDTCCAfWgAwIBAgIUXRmmtDH6xztumX/qzgaoDJS9+rMwDQYJKoZIhvcNAQEL
BQAwFjEUMBIGA1UEAwwLdGVzdC1jbGllbnQwHhcNMjYwODAzMTU0MTU3WhcNMzYw
NzMxMTU0MTU3WjAWMRQwEgYDVQQDDAt0ZXN0LWNsaWVudDCCASIwDQYJKoZIhvcN
AQEBBQADggEPADCCAQoCggEBAKYHCU+VHxNMs72KObxaacIuPRA9TaX/6qnQjIT3
L1LILqEBM/hqMJAbN1JkPjpKO8pgZc73YaTxZQ4/M15xosCn6BJ2/WuD+CxX4wW1
LTocMqvEsG9tx6ro/JnwxxUk1H9Y6K37PoGi5tQQ7/6RsKA5RvhZ3MpqC4+6J4bA
x0NG2lt2KCKvB/6dY1u7wrZqPS91CL5pvq0T8XplQ/la/qo19q10W6G1khSTaLyo
EUFZY60UYcPrszSChdKnt+Ou4pl4aNoB+IeCsILAuTorAOaagoQhPII5rUhr43iP
clndwMcPFlRnyuxxNSH6AJl1iBhCNkZAzL/PDVv00bjqIgsCAwEAAaNTMFEwHQYD
VR0OBBYEFD842rK26S3OI/jcQwDJsS5ngDMXMB8GA1UdIwQYMBaAFD842rK26S3O
I/jcQwDJsS5ngDMXMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQELBQADggEB
AIM4weN9yL6hTPDAVeq5mBONPXS9xvo99pGJwYwmpEGC+jVcjwYeFXe1UYC+HKGw
LtQXz/o66g6fRz7Ejfd+sgyqucW2JkHBJfoGFcZKg9mpq4ljCl8+fe9TnGPWgLFi
UQ3dgS0duKGzI+kzR25PMvzWFnvTucV9LQSjUpA3zRQ9J4zaz7jXIT2wOreQv7Uw
oPg2kvVojXHVX223yZon0qBbRB2tunNlMOkp+cFu/iBUCV13WUWaRcKqoEyTZD0g
t0rJBn2nEGefw/yZ/sAFKOHmyjyk7noaFu4WFGBkHH1wS0i/TZBvy+9qg1ZNq/Fo
yGLF50wFVWXGenm9FHJtFqM=
-----END CERTIFICATE-----
"""

_VALID_CLIENT_KEY_PEM = """\
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCmBwlPlR8TTLO9
ijm8WmnCLj0QPU2l/+qp0IyE9y9SyC6hATP4ajCQGzdSZD46SjvKYGXO92Gk8WUO
PzNecaLAp+gSdv1rg/gsV+MFtS06HDKrxLBvbceq6PyZ8McVJNR/WOit+z6BoubU
EO/+kbCgOUb4WdzKaguPuieGwMdDRtpbdigirwf+nWNbu8K2aj0vdQi+ab6tE/F6
ZUP5Wv6qNfatdFuhtZIUk2i8qBFBWWOtFGHD67M0goXSp7fjruKZeGjaAfiHgrCC
wLk6KwDmmoKEITyCOa1Ia+N4j3JZ3cDHDxZUZ8rscTUh+gCZdYgYQjZGQMy/zw1b
9NG46iILAgMBAAECggEAA3QrWhUiEQa2ySnyStweoxl5z7gBa4NICxb5irKRsMkq
nyglP/UFju83VrwbHJ9QCxpiQ8ya+BFwJrxjLIMfUvQAkecZHSl2T4XXL9aLBaXH
MBI8EWAD7VGXdPmwn9yk8a6UeI9nciREuliihXXbv27cQ8JVeNMn67+ASaoCUICa
OikL68kpkbuO3QKpspx4slX70MyDO+Yve9Y+5AmBSMDpwvaFKswiwNrxGK9dTpki
J8TcCQNexAFBLaSLmCJrXzS2AIdldMaWSh4UrRoZsf/NMmrGtSETzBqmVbZOORdP
ScvJlrPCTniUQpGoHUn9xTNvYObt+7wdz8nMQDbQsQKBgQDdaDux7XddfvVbAJLu
ZeXonz0y+/F5i07jTfe5jTz9fcPoDbHPvNJOPCHq6e9gG24n+DMOuAe5j7THnTxI
9k35JZ5iMnKB4kyw5+Pf5TRIGdXhkScz4ZmSodctdHtDwUpuXaSG6TMarYGst1mF
YBAos8icsUj7BnCJQaRwT3psHQKBgQC/978EAnCe0FAqzMou1U4Bakj06JbPAbTl
vDBwlNpIWrnw2osQ13+0EvYR3CYajz2Wa5Uf3s+cn+rwXSeaHPIXlyNIJJs7xuCM
bdoyPYipQijNGQmYexxcxqtJafuog0HBngqo/UrIHNg8lxUmLBtQxcQ5wNl72UWw
j48XDPneRwKBgCRceOlIsYDGV+8hEgBa9b4VYMydudOXQFZuOI/dlTWgUOssTJZs
UTGOCJf24VwsRRQFXAU/zez4n9zkgsEMylNvjSpdVJbmHmgzPSZJEyQAMjMATqrj
kwAU2izZ42CGPv4PHPUXGVB5TEGcPvR7iUvV8s1hBDZNoW+5OxNCyj01AoGAfO8j
5dwgp3szcWdufiRcbBdb++gTng2iSZG8hMibd1N0iAfzUbauaeedNeps8gQfNPI3
T1KXE3wQTvaRe38zH59BWwZX8QNxyHMF+oSJmH5yR2jwEcitoMO7XkAXhIhIF1Zf
4bNXI/2BzY0WOo2iCWNsXZng8PVqoYoMuhe71qkCgYEA2sbZerokHhm61lZCw0nu
gZ4z+wWaUeRbU0vpQOM04+sqZTsyARGO8glGwKDK90gCsQfJeLtzxWW1mFwrE7xw
ReiJ4xxtRhucn+cWiV7vATTnz4Z//xSL5QFioPRI+QOIH3dofwJsD5lW0KJtxAt8
S98MfX8P7bwrdNJAqU9MRf8=
-----END PRIVATE KEY-----
"""


def _write_cafile(tmp_path: Path) -> Path:
    cafile = tmp_path / "ca.crt"
    cafile.write_text(_VALID_CA_PEM, encoding="utf-8")
    return cafile


def _sasl_settings(*, cafile: str = "") -> BrokerSettings:
    return BrokerSettings(
        security_protocol="SASL_SSL",
        sasl_mechanism="SCRAM-SHA-256",
        sasl_plain_username="admin",
        sasl_plain_password="s3cret",
        ssl_cafile=cafile,
    )


def test_security_kwargs_plaintext() -> None:
    assert _kafka_security_kwargs(BrokerSettings()) == {
        "security_protocol": "PLAINTEXT"
    }


def test_security_kwargs_sasl_plaintext() -> None:
    settings = BrokerSettings(
        security_protocol="SASL_PLAINTEXT",
        sasl_mechanism="SCRAM-SHA-256",
        sasl_plain_username="admin",
        sasl_plain_password="s3cret",
    )
    assert _kafka_security_kwargs(settings) == {
        "security_protocol": "SASL_PLAINTEXT",
        "sasl_mechanism": "SCRAM-SHA-256",
        "sasl_plain_username": "admin",
        "sasl_plain_password": "s3cret",
    }


def test_security_kwargs_ssl(tmp_path: Path) -> None:
    cafile = _write_cafile(tmp_path)
    settings = BrokerSettings(security_protocol="SSL", ssl_cafile=str(cafile))
    kwargs = _kafka_security_kwargs(settings)
    assert kwargs["security_protocol"] == "SSL"
    assert isinstance(kwargs["ssl_context"], ssl.SSLContext)
    # aiokafka 0.14 accepts only ssl_context, never the file path kwargs.
    assert "ssl_cafile" not in kwargs
    assert "ssl_certfile" not in kwargs
    assert "ssl_keyfile" not in kwargs


def test_security_kwargs_sasl_ssl(tmp_path: Path) -> None:
    cafile = _write_cafile(tmp_path)
    kwargs = _kafka_security_kwargs(_sasl_settings(cafile=str(cafile)))
    assert kwargs["security_protocol"] == "SASL_SSL"
    assert kwargs["sasl_mechanism"] == "SCRAM-SHA-256"
    assert kwargs["sasl_plain_username"] == "admin"
    assert kwargs["sasl_plain_password"] == "s3cret"
    assert isinstance(kwargs["ssl_context"], ssl.SSLContext)
    assert "ssl_cafile" not in kwargs


def test_security_kwargs_sasl_ssl_with_client_cert(tmp_path: Path) -> None:
    cafile = _write_cafile(tmp_path)
    certfile = tmp_path / "client.crt"
    keyfile = tmp_path / "client.key"
    certfile.write_text(_VALID_CLIENT_CERT_PEM, encoding="utf-8")
    keyfile.write_text(_VALID_CLIENT_KEY_PEM, encoding="utf-8")
    settings = BrokerSettings(
        security_protocol="SASL_SSL",
        sasl_mechanism="SCRAM-SHA-256",
        sasl_plain_username="admin",
        sasl_plain_password="s3cret",
        ssl_cafile=str(cafile),
        ssl_certfile=str(certfile),
        ssl_keyfile=str(keyfile),
    )
    kwargs = _kafka_security_kwargs(settings)
    assert isinstance(kwargs["ssl_context"], ssl.SSLContext)


def _capture_constructor(monkeypatch: pytest.MonkeyPatch, module: str, attr: str) -> dict:
    captured: dict = {}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr(f"{module}.{attr}", FakeClient)
    return captured


def test_build_kafka_producer_passes_security_kwargs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cafile = _write_cafile(tmp_path)
    settings = _sasl_settings(cafile=str(cafile))
    captured = _capture_constructor(monkeypatch, "aiokafka", "AIOKafkaProducer")

    _build_kafka_producer(settings)

    assert captured["kwargs"]["security_protocol"] == "SASL_SSL"
    assert captured["kwargs"]["sasl_mechanism"] == "SCRAM-SHA-256"
    assert captured["kwargs"]["sasl_plain_username"] == "admin"
    assert captured["kwargs"]["sasl_plain_password"] == "s3cret"
    assert isinstance(captured["kwargs"]["ssl_context"], ssl.SSLContext)


def test_build_kafka_consumer_passes_security_kwargs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cafile = _write_cafile(tmp_path)
    settings = _sasl_settings(cafile=str(cafile))
    captured = _capture_constructor(monkeypatch, "aiokafka", "AIOKafkaConsumer")

    _build_kafka_consumer(settings, topic="cmd", group_id="grp")

    assert captured["kwargs"]["security_protocol"] == "SASL_SSL"
    assert captured["kwargs"]["sasl_mechanism"] == "SCRAM-SHA-256"
    assert captured["kwargs"]["sasl_plain_username"] == "admin"
    assert captured["kwargs"]["sasl_plain_password"] == "s3cret"
    assert isinstance(captured["kwargs"]["ssl_context"], ssl.SSLContext)


def test_build_lag_consumer_passes_security_kwargs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cafile = _write_cafile(tmp_path)
    settings = _sasl_settings(cafile=str(cafile))
    captured = _capture_constructor(monkeypatch, "aiokafka", "AIOKafkaConsumer")

    _build_lag_consumer(settings, group_id="grp")

    assert captured["kwargs"]["security_protocol"] == "SASL_SSL"
    assert captured["kwargs"]["sasl_mechanism"] == "SCRAM-SHA-256"
    assert captured["kwargs"]["sasl_plain_username"] == "admin"
    assert captured["kwargs"]["sasl_plain_password"] == "s3cret"
    assert isinstance(captured["kwargs"]["ssl_context"], ssl.SSLContext)


def test_build_kafka_admin_passes_security_kwargs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cafile = _write_cafile(tmp_path)
    settings = _sasl_settings(cafile=str(cafile))
    captured = _capture_constructor(
        monkeypatch, "aiokafka.admin", "AIOKafkaAdminClient"
    )

    _build_kafka_admin(settings)

    assert captured["kwargs"]["security_protocol"] == "SASL_SSL"
    assert captured["kwargs"]["sasl_mechanism"] == "SCRAM-SHA-256"
    assert captured["kwargs"]["sasl_plain_username"] == "admin"
    assert captured["kwargs"]["sasl_plain_password"] == "s3cret"
    assert isinstance(captured["kwargs"]["ssl_context"], ssl.SSLContext)
