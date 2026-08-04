"""Live SA identity outbox event -> RAG memory_service user_profiles proof.

Publishes a fresh ``identity.user.registered`` outbox event (exact SA schema and
serialization: an aiokafka producer keyed by ``user_id`` with ``sort_keys``
compact JSON, mirroring ``RedpandaIdentityEventPublisher.publish``) to
``identity.user.events`` and asserts the RAG memory worker's
``BrokerIdentitySource`` created the ``user_profiles`` row -- proven end-to-end
via ``read_profile``, which reads the same SQLite row the worker wrote.

Same container topology as the interop tests: the client runs inside a
throwaway container on ``rag-memory-test`` because Redpanda's INTERNAL listener
advertises ``redpanda-rag-local:19092``, which only containers on that network
resolve.

Requires only the RAG memory worker + broker (no retrieval workers or Qdrant),
and skips cleanly when the memory worker is up but its identity consumer is not
wired (``identity_mode != broker``).

Bring up:
    cd deployment
    REDIS_PASSWORD=<secret> SERVICE_AUTH_SIGNING_KEY=<secret> \
    docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.interop.yml \
      up -d memory
    RAG_LIVE_INFRA=1 python -m pytest tests/integration/test_sa_broker_interop_identity.py -q

Skip policy: skips cleanly when ``RAG_LIVE_INFRA != 1``, when the memory worker
is not ready or its ``identity_mode`` is not ``broker``, or when the simple_agent
checkout / Docker / network / image are missing. FAILS when the stack is up but
``read_profile`` does not reflect the published registered event -- that is the
integration failure this test exists to catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration._broker_interop_helpers import (
    require_live_infra,
    require_prereqs,
    run_client_in_container,
)

pytestmark = pytest.mark.live_infra

# Runs inside the throwaway client container (RAG image, /app = RAG code; SA
# checkout mounted at /sa). Publishes a fresh identity.user.registered outbox
# event and polls read_profile until the worker's BrokerIdentitySource has
# applied it to the SQLite user_profiles row.
_IDENTITY_SCRIPT = r"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

for _p in ("/sa/libs/service-auth/src", "/sa/services/conversation-server/src"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from aiokafka import AIOKafkaProducer  # noqa: E402
from simple_agent_service_auth import ServiceAuthSettings  # noqa: E402
from conversation_server.application.conversation_service import Actor  # noqa: E402
from conversation_server.infrastructure.memory_client import (  # noqa: E402
    MemoryBrokerClient,
    MemoryClientSettings,
)
from broker_service import (  # noqa: E402
    BrokerSettings,
    bootstrap_topics,
    create_redpanda_admin,
)

BOOTSTRAP = os.environ["REDPANDA_BOOTSTRAP_SERVERS"]
SIGNING_KEY = os.environ["SERVICE_AUTH_SIGNING_KEY"]
ISSUER = os.environ["SERVICE_AUTH_TOKEN_ISSUER"]
AUDIENCE = os.environ["SERVICE_AUTH_TOKEN_AUDIENCE"]
TRACEPARENT = "00-55555555555555555555555555555555-6666666666666666-01"

IDENTITY_TOPIC = "identity.user.events"

EXPECTED_BASIC_INFO = {
    "email": "identity-probe@example.com",
    "display_name": "Identity Probe User",
    "role": "tier_1",
    "account_status": "active",
}


async def _verify_identity() -> None:
    user_id = f"user_identity_{os.urandom(6).hex()}"
    event = {
        "event_id": f"evt_identity_{os.urandom(8).hex()}",
        "event_type": "identity.user.registered",
        "event_version": 1,
        "user_id": user_id,
        "identity_revision": 1,
        "email": EXPECTED_BASIC_INFO["email"],
        "display_name": EXPECTED_BASIC_INFO["display_name"],
        "role": EXPECTED_BASIC_INFO["role"],
        "account_status": EXPECTED_BASIC_INFO["account_status"],
        "occurred_at": "2026-08-04T00:00:00Z",
    }
    client = MemoryBrokerClient(
        MemoryClientSettings(
            client_mode="broker",
            command_topic="domain.memory.commands",
            result_topic="domain.memory.results",
            bootstrap_servers_env="REDPANDA_BOOTSTRAP_SERVERS",
        ),
        service_auth=ServiceAuthSettings(
            signing_key=SIGNING_KEY,
            issuer=ISSUER,
            audience=AUDIENCE,
            ttl_seconds=300,
            allowed_services=("conversation-server",),
        ),
        reply_timeout_seconds=30.0,
    )
    admin = create_redpanda_admin(
        BrokerSettings(
            bootstrap_servers=BOOTSTRAP,
            client_id=f"sa-identity-{os.urandom(4).hex()}",
            topic_prefix="",
        )
    )
    raw = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    actor = Actor(user_id=user_id, role="tier_1")
    try:
        await admin.start()
        await bootstrap_topics(admin, settings=admin.settings)
        # Mirrors RedpandaIdentityEventPublisher.publish exactly: aiokafka,
        # keyed by owner_user_id, sort_keys compact JSON.
        await raw.start()
        await raw.send_and_wait(
            IDENTITY_TOPIC,
            key=user_id.encode("utf-8"),
            value=json.dumps(event, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            ),
        )
        await raw.stop()
        await client.start()

        # The worker applies identity events asynchronously; poll read_profile
        # (the same SQLite row) until the registered event lands.
        basic_info: dict = {}
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            result = await client.read_profile(
                actor=actor,
                agent_id="agent_1",
                request_id="req_identity",
                traceparent=TRACEPARENT,
            )
            basic_info = dict((result.get("profile") or {}).get("basic_info") or {})
            if basic_info:
                break
            await asyncio.sleep(1)
        for field_name, expected in EXPECTED_BASIC_INFO.items():
            assert basic_info.get(field_name) == expected, (
                f"profile.basic_info[{field_name}] = {basic_info.get(field_name)!r}; "
                f"expected {expected!r} from identity.user.registered"
            )
        print(
            "SA identity.user.registered -> memory user_profiles PROVEN: "
            f"read_profile returned basic_info {json.dumps(basic_info, sort_keys=True)}"
        )
    finally:
        await client.close()
        await admin.stop()
        await raw.stop()


if __name__ == "__main__":
    asyncio.run(_verify_identity())
"""


def test_sa_identity_event_creates_user_profile(tmp_path: Path) -> None:
    """A fresh identity.user.registered event lands in the memory user_profiles."""
    require_live_infra()
    require_prereqs(need_identity=True)
    proc = run_client_in_container(tmp_path, _IDENTITY_SCRIPT, label="verify_identity")
    assert proc.returncode == 0, (
        "SA identity event -> RAG user_profiles proof failed:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "PROVEN" in proc.stdout
