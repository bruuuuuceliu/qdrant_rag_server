"""Memory document, chunk, and payload schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import require_non_empty
from retrieval_service.core.schemas.document import (
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryDocument(BaseDocument):
    memory_id: str
    owner_id: str
    content: str
    agent_id: str = ""
    run_id: str = ""
    data_type: str = "memory"
    memory_type: str = "semantic"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", self.document_id or self.memory_id)
        object.__setattr__(self, "data_type", self.data_type or "memory")
        BaseDocument.__post_init__(self)
        require_non_empty("memory_id", self.memory_id)
        require_non_empty("owner_id", self.owner_id)
        require_non_empty("content", self.content)
        require_non_empty("memory_type", self.memory_type)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryChunk(BaseChunk):
    memory_id: str
    owner_id: str
    agent_id: str = ""
    run_id: str = ""
    data_type: str = "memory"
    memory_type: str = "semantic"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", self.document_id or self.memory_id)
        object.__setattr__(self, "data_type", self.data_type or "memory")
        BaseChunk.__post_init__(self)
        require_non_empty("memory_id", self.memory_id)
        require_non_empty("owner_id", self.owner_id)
        require_non_empty("memory_type", self.memory_type)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryChunkPayload(BaseChunkPayload):
    memory_id: str
    owner_id: str
    agent_id: str = ""
    run_id: str = ""
    data_type: str = "memory"
    memory_type: str = "semantic"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_chunk(cls, chunk: MemoryChunk) -> "MemoryChunkPayload":
        return cls(
            payload_id=chunk.chunk_id,
            memory_id=chunk.memory_id,
            owner_id=chunk.owner_id,
            agent_id=chunk.agent_id,
            run_id=chunk.run_id,
            memory_type=chunk.memory_type,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            data_type=chunk.data_type,
            content_hash=chunk.content_hash,
            chunker_version=chunk.chunker_version,
            metadata=dict(chunk.metadata),
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", self.document_id or self.memory_id)
        object.__setattr__(self, "payload_id", self.payload_id or self.chunk_id)
        object.__setattr__(self, "data_type", self.data_type or "memory")
        BaseChunkPayload.__post_init__(self)
        require_non_empty("memory_id", self.memory_id)
        require_non_empty("owner_id", self.owner_id)
        require_non_empty("memory_type", self.memory_type)

    def point_identity(self) -> tuple[str, ...]:
        return (
            self.owner_id,
            self.agent_id,
            self.run_id,
            self.memory_id,
            self.data_type,
            str(self.chunk_index),
            self.chunker_version,
        )

    def to_qdrant_payload(self) -> dict[str, Any]:
        payload = BaseChunkPayload.to_qdrant_payload(self)
        payload.update(
            {
                "memory_id": self.memory_id,
                "owner_id": self.owner_id,
                "agent_id": self.agent_id,
                "run_id": self.run_id,
                "memory_type": self.memory_type,
            }
        )
        return payload
