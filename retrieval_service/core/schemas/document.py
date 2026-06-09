"""Universal document, chunk, and payload primitives.

These classes intentionally avoid project-RAG concepts such as project IDs,
knowledge-base IDs, and document ownership policy. Concrete retrieval services
should extend them in their own schema packages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import require_non_empty


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseDocument:
    """A neutral source record that can be transformed into retrievable chunks."""

    document_id: str = ""
    source_uri: str = ""
    content_type: str = "text/plain"
    data_type: str = "document"
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("document_id", self.document_id)
        require_non_empty("content_type", self.content_type)
        require_non_empty("data_type", self.data_type)


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseChunk:
    """A neutral text unit ready for embedding or other retrieval indexing."""

    chunk_id: str
    chunk_index: int
    text: str
    document_id: str = ""
    data_type: str = "document"
    content_hash: str = ""
    chunker_version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("chunk_id", self.chunk_id)
        require_non_empty("text", self.text)
        require_non_empty("data_type", self.data_type)
        require_non_empty("chunker_version", self.chunker_version)
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseChunkPayload:
    """A neutral payload shape that can be rendered for vector backends."""

    payload_id: str = ""
    chunk_id: str
    chunk_index: int
    text: str
    document_id: str = ""
    data_type: str = "document"
    content_hash: str = ""
    embedding_version: str = ""
    chunker_version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_chunk(cls, chunk: BaseChunk) -> "BaseChunkPayload":
        return cls(
            payload_id=chunk.chunk_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            document_id=chunk.document_id,
            data_type=chunk.data_type,
            content_hash=chunk.content_hash,
            chunker_version=chunk.chunker_version,
            metadata=dict(chunk.metadata),
        )

    def __post_init__(self) -> None:
        require_non_empty("payload_id", self.payload_id)
        require_non_empty("chunk_id", self.chunk_id)
        require_non_empty("text", self.text)
        require_non_empty("data_type", self.data_type)
        require_non_empty("chunker_version", self.chunker_version)
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")

    def point_identity(self) -> tuple[str, ...]:
        """Return a stable identity tuple for deterministic vector point IDs."""

        return (
            self.payload_id,
            self.chunk_id,
            self.data_type,
            str(self.chunk_index),
            self.chunker_version,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "payload_id": self.payload_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "data_type": self.data_type,
            "content_hash": self.content_hash,
            "embedding_version": self.embedding_version,
            "chunker_version": self.chunker_version,
            "metadata": dict(self.metadata),
        }

    def to_qdrant_payload(self) -> dict[str, Any]:
        return self.to_payload()
