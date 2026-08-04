"""Live SA broker-mode client <-> RAG FULL memory.lookup path over a real broker.

Proves the entire SA<->RAG memory retrieval path end-to-end: a ``simple_agent``
``MemoryBrokerClient`` records a session and two messages, compresses them, the
RAG memory worker hands the records to the retrieval-index worker via
``helper.retrieval_index.commands`` (``memory_ingest``), which embeds and
indexes them into the Qdrant ``agent_memory`` collection, and a later
``memory.lookup`` (a real vector search through the retrieval worker) returns
the recorded content.

This is strictly stronger than ``test_sa_broker_interop.py``: session/message/
compress never read the vector store. The assertions here are on REAL returned
content from the Qdrant index -- this conversation's indexed message hits
(``msg_*``) and the indexed compress summary (``mem_sum_*``) -- never a stub.

Same topology as the committed interop test: the client runs inside a
throwaway container on ``rag-memory-test`` because Redpanda's INTERNAL listener
advertises ``redpanda-rag-local:19092``, which only containers on that network
resolve.

Required stack (all on ONE embedding configuration):
    cd deployment
    REDIS_PASSWORD=<secret> SERVICE_AUTH_SIGNING_KEY=<secret> \
    RAG_EMBEDDING_PROVIDER=deterministic RAG_EMBEDDING_MODEL=deterministic-hash \
    RAG_EMBEDDING_DIMENSION=384 \
    docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.interop.yml \
      up -d qdrant retrieval-index retrieval memory
    RAG_LIVE_INFRA=1 python -m pytest tests/integration/test_sa_broker_interop_lookup.py -q

The whole stack must share one embedding configuration: a stale
``agent_memory`` collection built with a different dimension than the running
embedding model degrades ``memory.lookup`` chat_history to empty by design
(memory_service degrades a dimension mismatch rather than failing), so delete
stale collections before re-running with a different dimension.

Skip policy: skips cleanly when ``RAG_LIVE_INFRA != 1``, when any retrieval
prerequisite (qdrant, retrieval, retrieval-index, memory broker index/search
modes) is absent or not ready, or when the simple_agent checkout / Docker /
network / image are missing. FAILS when the stack is up but ``memory.lookup``
does not return the recorded content -- that is the integration failure this
test exists to catch.
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
# checkout mounted at /sa). Records + compresses this run's own messages, then
# polls memory.lookup until the async index hand-off lands in Qdrant.
_LOOKUP_SCRIPT = r"""
from __future__ import annotations

import asyncio
import os
import sys
import time

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
)

BOOTSTRAP = os.environ["REDPANDA_BOOTSTRAP_SERVERS"]
SIGNING_KEY = os.environ["SERVICE_AUTH_SIGNING_KEY"]
ISSUER = os.environ["SERVICE_AUTH_TOKEN_ISSUER"]
AUDIENCE = os.environ["SERVICE_AUTH_TOKEN_AUDIENCE"]
TRACEPARENT = "00-33333333333333333333333333333333-4444444444444444-01"

LOOKUP_QUERY = "dietary gluten-free preference"
USER_TEXT = "user mentioned a dietary preference for gluten-free pasta"
ASSISTANT_TEXT = "noted, gluten-free preference recorded"


async def _verify_lookup() -> None:
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
            client_id=f"sa-lookup-{os.urandom(4).hex()}",
            topic_prefix="",
        )
    )
    conversation_id = f"conv_lookup_{os.urandom(6).hex()}"
    user_id = f"user_lookup_{os.urandom(6).hex()}"
    actor = Actor(user_id=user_id, role="tier_1")
    try:
        await admin.start()
        await bootstrap_topics(admin, settings=admin.settings)
        await client.start()

        await client.record_session_start(
            actor=actor,
            conversation_id=conversation_id,
            agent_id="agent_1",
            request_id="req_lookup",
            traceparent=TRACEPARENT,
        )
        await client.record_message(
            actor=actor,
            message_id=f"msg_{conversation_id}_1",
            conversation_id=conversation_id,
            agent_id="agent_1",
            role="user",
            sequence_number=1,
            content=USER_TEXT,
            created_at="2026-08-04T00:00:00Z",
            request_id="req_lookup",
            traceparent=TRACEPARENT,
        )
        await client.record_message(
            actor=actor,
            message_id=f"msg_{conversation_id}_2",
            conversation_id=conversation_id,
            agent_id="agent_1",
            role="assistant",
            sequence_number=2,
            content=ASSISTANT_TEXT,
            created_at="2026-08-04T00:00:00Z",
            request_id="req_lookup",
            traceparent=TRACEPARENT,
        )
        compress_result = await client.compress(
            actor=actor,
            conversation_id=conversation_id,
            agent_id="agent_1",
            start_sequence=1,
            end_sequence=2,
            keep_recent=0,
            request_id="req_lookup",
            traceparent=TRACEPARENT,
        )
        assert compress_result.get("memory_id", "").startswith("mem_sum_"), compress_result
        assert compress_result.get("condensed_context"), compress_result

        # Indexing is a fire-and-forget projection (SQLite stays authoritative);
        # poll memory.lookup until the vector hand-off for ALL this run's records
        # lands in Qdrant. The message ingests are queued during record_message,
        # but the compress-summary ingest is queued last (right before compress
        # replies), so the first lookup can already return the messages while the
        # summary is still being indexed. Each lookup is a fresh request/reply
        # through the retrieval worker, so this loop is both the wait and the
        # assertion under test.
        def expected(hits: list[dict]) -> bool:
            message_hits = [
                h for h in hits if str(h.get("source_id", "")).startswith("msg_")
            ]
            summary_hits = [
                h for h in hits if str(h.get("source_id", "")).startswith("mem_sum_")
            ]
            return bool(
                message_hits
                and summary_hits
                and any(
                    str(h.get("session_id", "")) == conversation_id
                    and "gluten-free" in str(h.get("text", ""))
                    for h in message_hits + summary_hits
                )
            )

        result: dict = {}
        hits: list[dict] = []
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            try:
                result = await client.lookup(
                    actor=actor,
                    query=LOOKUP_QUERY,
                    sources=["chat_history"],
                    # Filter to THIS run's conversation so repeated live runs stay
                    # deterministic: the deterministic-hash embedding produces
                    # near-identical vectors across runs, so an unfiltered
                    # top-k search over the shared collection could rank this
                    # run's hits out of the default top-5 on later runs.
                    session_ids=[conversation_id],
                    agent_id="agent_1",
                    request_id="req_lookup",
                    traceparent=TRACEPARENT,
                )
            except MemoryClientError as exc:
                # A transient unavailable/upstream_error while workers warm up
                # is retried; anything else is a real failure.
                if exc.retryable:
                    await asyncio.sleep(2)
                    continue
                raise
            hits = list((result.get("results") or {}).get("chat_history") or [])
            if expected(hits):
                break
            await asyncio.sleep(2)

        assert hits, (
            "memory.lookup returned no chat_history hits after the index "
            "hand-off; full lookup path broken"
        )
        assert (result.get("consulted") or {}).get("chat_history") is True, result
        message_hits = [
            h for h in hits if str(h.get("source_id", "")).startswith("msg_")
        ]
        summary_hits = [
            h for h in hits if str(h.get("source_id", "")).startswith("mem_sum_")
        ]
        assert message_hits, f"no indexed message hits in lookup: {hits}"
        assert summary_hits, f"no indexed compress-summary hit in lookup: {hits}"
        assert any(
            str(h.get("session_id", "")) == conversation_id
            and "gluten-free" in str(h.get("text", ""))
            for h in message_hits
        ), f"no message from this conversation returned: {hits}"
        assert any(
            str(h.get("session_id", "")) == conversation_id
            and "gluten-free" in str(h.get("text", ""))
            for h in summary_hits
        ), f"no compress summary from this conversation returned: {hits}"
        print(
            "SA <-> RAG full memory.lookup PROVEN: "
            f"{len(message_hits)} message + {len(summary_hits)} summary hit(s) "
            "returned from the Qdrant agent_memory collection"
        )
    finally:
        await client.close()
        await admin.stop()


if __name__ == "__main__":
    asyncio.run(_verify_lookup())
"""


def test_sa_broker_client_full_memory_lookup(tmp_path: Path) -> None:
    """SA client records + compresses and memory.lookup returns the content."""
    require_live_infra()
    require_prereqs(need_retrieval=True)
    proc = run_client_in_container(tmp_path, _LOOKUP_SCRIPT, label="verify_lookup")
    assert proc.returncode == 0, (
        "SA broker client -> RAG full memory.lookup failed:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "PROVEN" in proc.stdout
