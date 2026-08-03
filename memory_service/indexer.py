"""Memory vector-indexer port.

``MemoryIndexer`` is a fire-and-forget port that hands memory records to the
retrieval service for vector indexing. ``BrokerMemoryIndexer`` publishes a
``memory_ingest`` helper command; ``FakeMemoryIndexer`` records calls for tests.
SQLite remains the source of truth; indexing is an async best-effort projection.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from retrieval_service.memory.schemas.documents import (
    MemoryChunk,
    MemoryChunkPayload,
)
from shared.contracts import (
    HelperCommandPayload,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
)
from memory_service.models import MemoryRecord


class MemoryIndexError(RuntimeError):
    """Base error for memory index hand-off failures."""


class MemoryIndexUnavailableError(MemoryIndexError):
    """Raised when the retrieval index helper is unreachable."""


class MemoryIndexer(Protocol):
    """Port: index memory records for semantic retrieval (fire-and-forget)."""

    async def index(self, records: list[MemoryRecord]) -> None:
        ...


class FakeMemoryIndexer:
    """Deterministic in-process indexer recording indexed records."""

    def __init__(self) -> None:
        self.indexed: list[list[MemoryRecord]] = []

    async def index(self, records: list[MemoryRecord]) -> None:
        self.indexed.append(list(records))


class BrokerMemoryIndexer:
    """Publishes ``memory_ingest`` helper commands to the retrieval service."""

    def __init__(
        self,
        *,
        producer: MessageProducer,
        response_topic: str = TOPICS.helper_retrieval_index_results,
        collection_name: str = "agent_memory",
    ) -> None:
        self._producer = producer
        self._response_topic = response_topic
        self._collection_name = collection_name

    async def index(self, records: list[MemoryRecord]) -> None:
        if not records:
            return
        chunks: list[MemoryChunk] = []
        payloads: list[MemoryChunkPayload] = []
        for record in records:
            chunk = _chunk_from_record(record)
            chunks.append(chunk)
            payloads.append(MemoryChunkPayload.from_chunk(chunk))
        task_id = records[0].memory_id
        envelope = MessageEnvelope.create(
            producer="memory_service",
            message_type=MessageType.HELPER_COMMAND,
            data_type="agent_memory",
            task_id=task_id,
            correlation_id=f"mem_index_{task_id}",
            payload=HelperCommandPayload(
                operation="memory_ingest",
                helper=TOPICS.helper_retrieval_index_commands,
                attempt=1,
                plan={
                    "collection_name": self._collection_name,
                    "chunks": [_mapping(chunk) for chunk in chunks],
                    "payloads": [_mapping(payload) for payload in payloads],
                    "response_topic": self._response_topic,
                },
                source_message_id=task_id,
            ).to_payload(),
        )
        try:
            await self._producer.publish(
                TOPICS.helper_retrieval_index_commands,
                envelope,
                key=task_id,
            )
        except Exception as exc:
            raise MemoryIndexUnavailableError(f"memory index publish failed: {exc}") from exc


def _chunk_from_record(record: MemoryRecord) -> MemoryChunk:
    chunk_id = f"{record.memory_id}:0"
    return MemoryChunk(
        chunk_id=chunk_id,
        chunk_index=0,
        text=record.content,
        memory_id=record.memory_id,
        owner_id=record.owner_user_id,
        agent_id=record.agent_id,
        document_id=record.memory_id,
        memory_type="semantic",
        metadata=_record_metadata(record),
    )


def _record_metadata(record: MemoryRecord) -> dict[str, Any]:
    metadata: dict[str, Any] = {"kind": record.kind}
    if record.session_id:
        metadata["session_id"] = record.session_id
    if record.covered_from is not None:
        metadata["covered_from"] = record.covered_from
    if record.covered_to is not None:
        metadata["covered_to"] = record.covered_to
    return metadata


def _mapping(value: Any) -> dict[str, Any]:
    return asdict(value)
