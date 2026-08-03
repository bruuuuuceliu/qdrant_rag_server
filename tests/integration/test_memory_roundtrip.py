"""In-process memory compress→index→lookup round-trip (no real broker).

Drives the full memory operation set through a shared in-memory envelope bus:
session.start → message.record → memory.compress → memory.lookup. The index
hand-off and semantic search are fake in-process ports, so this proves the
handler assembly (AC-5, AC-6, AC-7) without broker or Qdrant dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from memory_service.compression import CondenseV1Policy
from memory_service.domain_handler import MemoryDomainHandler
from memory_service.identity import FakeIdentitySource
from memory_service.indexer import FakeMemoryIndexer
from memory_service.repository import MemoryInMemoryRepository
from memory_service.searcher import FakeMemorySearcher
from shared.contracts import MessageEnvelope, MessageType, TOPICS
from tests.memory.conftest import command


@dataclass
class EnvelopeBus:
    """Minimal in-memory bus capturing published result envelopes."""

    published: list[tuple[str, MessageEnvelope, str]] = field(default_factory=list)

    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        self.published.append((topic, envelope, key))


@pytest.fixture
async def memory_handler() -> MemoryDomainHandler:
    repository = MemoryInMemoryRepository()
    identity = FakeIdentitySource(repository)
    return MemoryDomainHandler(
        repository=repository,
        compression=CondenseV1Policy(),
        indexer=FakeMemoryIndexer(),
        searcher=FakeMemorySearcher(),
        identity_source=identity,
        producer=None,
    )


async def test_memory_roundtrip_compress_then_lookup(memory_handler) -> None:
    await memory_handler._identity_source.seed()
    bus = EnvelopeBus()
    memory_handler._producer = bus

    # Session + messages
    await memory_handler.handle(
        command("session.start", {"session_id": "con_1", "agent_id": "agent_1"})
    )
    for seq in range(1, 4):
        await memory_handler.handle(
            command(
                "message.record",
                {
                    "message_id": f"msg_{seq}",
                    "session_id": "con_1",
                    "agent_id": "agent_1",
                    "role": "user",
                    "sequence_number": seq,
                    "content": f"user discussed refund policy in message {seq}",
                },
            )
        )

    # Compress the whole span
    compressed = await memory_handler.handle(
        command("memory.compress", {"session_id": "con_1", "start_sequence": 1, "end_sequence": 3})
    )
    payload = compressed.payload["result"]
    assert payload["condensed_context"]
    assert payload["memory_id"].startswith("mem_sum_")
    assert payload["covered_range"] == {"from": 1, "to": 3}

    # Dedup: same span → same memory_id, replayed
    again = await memory_handler.handle(
        command("memory.compress", {"session_id": "con_1", "start_sequence": 1, "end_sequence": 3})
    )
    assert again.payload["result"]["memory_id"] == payload["memory_id"]
    assert again.payload["result"]["replayed"] is True

    # Lookup returns the summary under chat_history (scoped to the session so the
    # compression-summary merge path runs)
    lookup = await memory_handler.handle(
        command(
            "memory.lookup",
            {"query": "refund", "sources": ["chat_history"], "session_ids": ["con_1"]},
        )
    )
    result = lookup.payload["result"]
    assert result["consulted"] == {"chat_history": True}
    summary_items = [
        item
        for item in result["results"]["chat_history"]
        if item["source_id"].startswith("mem_sum_")
    ]
    assert summary_items, "compressed summary should surface in chat_history lookup"

    # Every command published a DOMAIN_RESULT on the memory results topic
    topics = {topic for topic, _, _ in bus.published}
    assert TOPICS.domain_memory_results in topics
