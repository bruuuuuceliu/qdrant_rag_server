"""Live SA broker-mode client ↔ RAG memory_service interop over a real broker.

Proves the two-repo memory integration end-to-end over a real Redpanda broker:
simple_agent's real ``MemoryBrokerClient`` (imported from the simple_agent
checkout, not a copy) publishes ``domain.memory.commands`` and the RAG
``memory_service`` worker answers on ``domain.memory.results``.

Why the client runs inside a throwaway container
------------------------------------------------
The production Redpanda INTERNAL listener advertises
``redpanda-rag-local:19092`` (the shared ``rag-memory-test`` network's DNS
alias), which the host machine cannot resolve. A host-run aiokafka client would
bootstrap to ``127.0.0.1:19092`` and then fail to reach the advertised node
address. Running the client in a container attached to ``rag-memory-test`` (the
exact topology simple_agent production containers use) makes
``redpanda-rag-local:19092`` resolve natively, so this test exercises the real
production transport path.

Exact bring-up steps (RAG production compose on the interop override)
--------------------------------------------------------------------
    cd deployment
    REDIS_PASSWORD=<secret> SERVICE_AUTH_SIGNING_KEY=<secret> \
    SERVICE_AUTH_TOKEN_ISSUER=simple-agent-local \
    RAG_EMBEDDING_PROVIDER=deterministic RAG_EMBEDDING_MODEL=deterministic-hash \
    RAG_EMBEDDING_DIMENSION=384 \
    docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.interop.yml \
      up -d memory retrieval-index retrieval
    RAG_LIVE_INFRA=1 python -m pytest tests/integration/test_sa_broker_interop.py -q

Notes on the required env:

* ``SERVICE_AUTH_SIGNING_KEY`` must be the same value on both sides. Both
  production composes now default ``SERVICE_AUTH_TOKEN_ISSUER`` to
  ``simple-agent-local`` (matching SA's ``x-service-auth`` anchor), so the
  worker verifies the issuer SA actually mints. The explicit
  ``SERVICE_AUTH_TOKEN_ISSUER=simple-agent-local`` above is belt-and-suspenders;
  this test reads the same env for the client, so a drift is a real assertion,
  not a harness artifact.

* On a machine where ``examples/local/run-all.sh`` already created the global
  ``rag-memory-test`` network with ``docker network create`` (no compose label),
  the production compose refuses to adopt it. Add a temporary override that
  marks the network ``external: true`` (compose then uses the existing
  network). On a fresh machine where the RAG compose creates the network first,
  the extra override is unnecessary.

Skip policy: skips cleanly when ``RAG_LIVE_INFRA != 1``, the simple_agent
checkout is absent, Docker is unavailable, the ``rag-memory-test`` network or
the memory worker is not up, or the RAG image is not built. Fails when the stack
IS up but the round-trip breaks (e.g. signing-key or issuer drift) -- that is the
integration failure this test exists to catch.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.live_infra

# simple_agent checkout (read-only mount into the client container).
SIMPLE_AGENT_ROOT = Path(os.environ.get("SIMPLE_AGENT_ROOT", "/home/bruce/workspace/simple_agent"))
RAG_IMAGE = os.environ.get("RAG_INTEROP_IMAGE", "qdrant-rag-server:latest")
NETWORK = os.environ.get("RAG_INTEROP_NETWORK", "rag-memory-test")
MEMORY_READYZ_URL = os.environ.get("RAG_MEMORY_READYZ_URL", "http://127.0.0.1:9012/readyz")
BOOTSTRAP = os.environ.get("REDPANDA_BOOTSTRAP_SERVERS", "redpanda-rag-local:19092")
SIGNING_KEY = os.environ.get("SERVICE_AUTH_SIGNING_KEY", "")
ISSUER = os.environ.get("SERVICE_AUTH_TOKEN_ISSUER", "simple-agent-local")
AUDIENCE = os.environ.get("SERVICE_AUTH_TOKEN_AUDIENCE", "simple-agent-internal")

# Runs inside the throwaway client container (RAG image, /app = RAG code; SA
# checkout mounted at /sa). Reads the interop env from the docker run command.
_CLIENT_SCRIPT = r"""
from __future__ import annotations

import asyncio
import json
import os
import sys

for _p in ("/sa/libs/service-auth/src", "/sa/services/conversation-server/src"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from simple_agent_service_auth import ServiceAuthSettings  # noqa: E402
from conversation_server.application.conversation_service import Actor  # noqa: E402
from conversation_server.infrastructure.memory_client import (  # noqa: E402
    MemoryBrokerClient,
    MemoryClientError,
    MemoryClientSettings,
)
from broker_service import (  # noqa: E402
    BrokerSettings,
    bootstrap_topics,
    create_redpanda_admin,
    create_redpanda_consumer,
)
from shared.contracts import TOPICS, MessageType  # noqa: E402

BOOTSTRAP = os.environ["REDPANDA_BOOTSTRAP_SERVERS"]
SIGNING_KEY = os.environ["SERVICE_AUTH_SIGNING_KEY"]
ISSUER = os.environ["SERVICE_AUTH_TOKEN_ISSUER"]
AUDIENCE = os.environ["SERVICE_AUTH_TOKEN_AUDIENCE"]
EXPECT_REJECT = os.environ.get("INTEROP_EXPECT_REJECT", "0") == "1"

TRACEPARENT = "00-11111111111111111111111111111111-2222222222222222-01"


async def _consume_until(consumer: object, deadline_seconds: float = 20.0) -> object:
    # Read the next results-topic message, retrying the group-join/rebalance
    # timeout window a fresh consumer can hit. (No docstring: embedded in a raw
    # string, so triple quotes would terminate it.)
    import time as _time

    deadline = _time.monotonic() + deadline_seconds
    while _time.monotonic() < deadline:
        try:
            return await consumer.consume(TOPICS.domain_memory_results, timeout_seconds=8)
        except Exception:  # noqa: BLE001 - transient rebalance timeouts
            continue
    raise AssertionError("timed out waiting for a message on domain.memory.results")


def _client(signing_key: str | None = None) -> MemoryBrokerClient:
    service_auth = ServiceAuthSettings(
        signing_key=signing_key if signing_key is not None else SIGNING_KEY,
        issuer=ISSUER,
        audience=AUDIENCE,
        ttl_seconds=300,
        allowed_services=("conversation-server",),
    )
    return MemoryBrokerClient(
        MemoryClientSettings(
            client_mode="broker",
            command_topic="domain.memory.commands",
            result_topic="domain.memory.results",
            bootstrap_servers_env="REDPANDA_BOOTSTRAP_SERVERS",
        ),
        service_auth=service_auth,
        reply_timeout_seconds=25.0,
    )


async def _verify_roundtrip() -> None:
    client = _client()
    broker_settings = BrokerSettings(
        bootstrap_servers=BOOTSTRAP,
        client_id=f"sa-interop-{os.urandom(4).hex()}",
        topic_prefix="",
    )
    result_consumer = create_redpanda_consumer(
        broker_settings,
        topic=TOPICS.domain_memory_results,
        group_id=f"sa-interop-res-{os.urandom(6).hex()}",
    )
    admin = create_redpanda_admin(broker_settings)
    conversation_id = f"interop_{os.urandom(6).hex()}"
    actor = Actor(user_id="user_interop", role="tier_1")
    try:
        await admin.start()
        await bootstrap_topics(admin, settings=broker_settings)
        await client.start()
        await result_consumer.start()

        await client.record_session_start(
            actor=actor,
            conversation_id=conversation_id,
            agent_id="agent_1",
            request_id="req_interop",
            traceparent=TRACEPARENT,
        )
        # The results topic accumulates across live runs, so read until this
        # session's own DOMAIN_RESULT shows up (bounded; present messages are
        # read immediately).
        reply = None
        for _ in range(300):
            envelope = await _consume_until(result_consumer)
            result = (envelope.payload or {}).get("result") or {}
            if envelope.payload.get("operation") == "session.start" and result.get(
                "session", {}
            ).get("session_id") == conversation_id:
                reply = envelope
                break
        assert reply is not None, "no session.start DOMAIN_RESULT on domain.memory.results"
        assert reply.message_type == MessageType.DOMAIN_RESULT, reply.message_type
        assert reply.payload["result"]["created"] is True

        # Unique message ids per run: a fixed id would trip the worker's
        # (owner_user_id, message_id) idempotency check on a re-run and the
        # message would not be recorded into this fresh session.
        await client.record_message(
            actor=actor,
            message_id=f"msg_{conversation_id}_1",
            conversation_id=conversation_id,
            agent_id="agent_1",
            role="user",
            sequence_number=1,
            content="user mentioned a dietary preference for gluten-free",
            created_at="2026-08-04T00:00:00Z",
            request_id="req_interop",
            traceparent=TRACEPARENT,
        )
        await client.record_message(
            actor=actor,
            message_id=f"msg_{conversation_id}_2",
            conversation_id=conversation_id,
            agent_id="agent_1",
            role="assistant",
            sequence_number=2,
            content="noted, gluten-free preference recorded",
            created_at="2026-08-04T00:00:00Z",
            request_id="req_interop",
            traceparent=TRACEPARENT,
        )

        compress_result = await client.compress(
            actor=actor,
            conversation_id=conversation_id,
            agent_id="agent_1",
            start_sequence=1,
            end_sequence=2,
            keep_recent=0,
            request_id="req_interop",
            traceparent=TRACEPARENT,
        )
        assert compress_result.get("memory_id", "").startswith("mem_sum_"), compress_result
        assert compress_result.get("condensed_context"), compress_result
        assert compress_result.get("covered_range") == {"from": 1, "to": 2}, compress_result
        print("SA <-> RAG memory round-trip PROVEN over real broker")
    finally:
        await client.close()
        await result_consumer.stop()
        await admin.stop()


async def _verify_rejection() -> None:
    # A token minted with a drifted signing key must be rejected (spec
    # acceptance #9: corrupt the key on one side -> 401/403). Uses the SA
    # client's own request/reply path (no separate result consumer needed).
    client = _client(signing_key=SIGNING_KEY + "-drifted")
    admin = create_redpanda_admin(
        BrokerSettings(
            bootstrap_servers=BOOTSTRAP,
            client_id=f"sa-reject-{os.urandom(4).hex()}",
            topic_prefix="",
        )
    )
    actor = Actor(user_id="user_wrongkey", role="tier_1")
    try:
        await admin.start()
        await bootstrap_topics(admin, settings=admin.settings)
        await client.start()
        try:
            await client.read_profile(
                actor=actor,
                agent_id="agent_1",
                request_id="req_reject",
                traceparent=TRACEPARENT,
            )
        except MemoryClientError as exc:
            assert exc.code in ("unauthorized", "forbidden"), exc
            print("drifted-key token REJECTED (auth enforced)")
            return
        raise AssertionError("drifted-key token was NOT rejected")
    finally:
        await client.close()
        await admin.stop()


async def main() -> None:
    if EXPECT_REJECT:
        await _verify_rejection()
    else:
        await _verify_roundtrip()


if __name__ == "__main__":
    asyncio.run(main())
"""


def _require_live_infra() -> None:
    if os.environ.get("RAG_LIVE_INFRA") != "1":
        pytest.skip("set RAG_LIVE_INFRA=1 to run live infrastructure tests")


def _require_prereqs() -> None:
    if not (SIMPLE_AGENT_ROOT / "libs/service-auth/src").is_dir() or not (
        SIMPLE_AGENT_ROOT / "services/conversation-server/src"
    ).is_dir():
        pytest.skip(
            f"simple_agent checkout not present at {SIMPLE_AGENT_ROOT}; "
            "skipping SA<->RAG broker interop"
        )
    if not SIGNING_KEY:
        pytest.skip(
            "SERVICE_AUTH_SIGNING_KEY is required and must match the RAG memory "
            "worker's SERVICE_AUTH_SIGNING_KEY"
        )
    if shutil.which("docker") is None:
        pytest.skip("docker is not available")
    inspect_net = subprocess.run(
        ["docker", "network", "inspect", NETWORK], capture_output=True, text=True
    )
    if inspect_net.returncode != 0:
        pytest.skip(
            f"docker network {NETWORK!r} not present; bring up the RAG production "
            "compose first (see module docstring)"
        )
    try:
        with urllib.request.urlopen(MEMORY_READYZ_URL, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        if '"ready":true' not in body:
            pytest.skip(f"RAG memory worker not ready at {MEMORY_READYZ_URL}: {body}")
    except Exception as exc:  # noqa: BLE001 - any unreachability means skip
        pytest.skip(f"RAG memory worker not reachable at {MEMORY_READYZ_URL}: {exc}")
    inspect_image = subprocess.run(
        ["docker", "image", "inspect", RAG_IMAGE], capture_output=True
    )
    if inspect_image.returncode != 0:
        pytest.skip(f"RAG image {RAG_IMAGE!r} not built")


def _run_client_in_container(tmp_path: Path, *, expect_reject: bool) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "verify_interop.py"
    script.write_text(_CLIENT_SCRIPT, encoding="utf-8")
    cmd = [
        "docker", "run", "--rm",
        "--network", NETWORK,
        "-e", f"REDPANDA_BOOTSTRAP_SERVERS={BOOTSTRAP}",
        "-e", f"SERVICE_AUTH_SIGNING_KEY={SIGNING_KEY}",
        "-e", f"SERVICE_AUTH_TOKEN_ISSUER={ISSUER}",
        "-e", f"SERVICE_AUTH_TOKEN_AUDIENCE={AUDIENCE}",
        "-e", f"INTEROP_EXPECT_REJECT={'1' if expect_reject else '0'}",
        "-v", f"{SIMPLE_AGENT_ROOT}:/sa:ro",
        "-v", f"{script}:/app/verify_interop.py:ro",
        "--entrypoint", "python3",
        RAG_IMAGE,
        "/app/verify_interop.py",
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=240)


def test_sa_broker_client_memory_roundtrip(tmp_path: Path) -> None:
    """SA MemoryBrokerClient records a session + messages and RAG answers."""
    _require_live_infra()
    _require_prereqs()
    proc = _run_client_in_container(tmp_path, expect_reject=False)
    assert proc.returncode == 0, (
        "SA broker client -> RAG memory round-trip failed:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "PROVEN" in proc.stdout


def test_sa_broker_client_drifted_signing_key_rejected(tmp_path: Path) -> None:
    """A token minted with a drifted key is rejected by RAG memory_service."""
    _require_live_infra()
    _require_prereqs()
    proc = _run_client_in_container(tmp_path, expect_reject=True)
    assert proc.returncode == 0, (
        "drifted-key rejection probe failed:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "REJECTED" in proc.stdout
