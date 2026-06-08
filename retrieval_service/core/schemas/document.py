"""Document and chunk domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import (
    Visibility,
    normalize_kb_id,
    require_non_empty,
    validate_visibility,
)


@dataclass(frozen=True, slots=True)
class BaseDocument:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    source_uri: str
    content_type: str
    data_type: str = "document"
    visibility: str = Visibility.PRIVATE
    content_hash: str = ""
    embedding_version: str = ""
    chunker_version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        object.__setattr__(self, "kb_id", normalize_kb_id(self.kb_id))
        require_non_empty("doc_id", self.doc_id)
        require_non_empty("source_uri", self.source_uri)
        require_non_empty("content_type", self.content_type)
        require_non_empty("data_type", self.data_type)
        validate_visibility(self.visibility)
        require_non_empty("chunker_version", self.chunker_version)


@dataclass(frozen=True, slots=True)
class BaseChunk:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    chunk_id: str
    chunk_index: int
    text: str
    data_type: str = "document"
    visibility: str = Visibility.PRIVATE
    content_hash: str = ""
    embedding_version: str = ""
    chunker_version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        object.__setattr__(self, "kb_id", normalize_kb_id(self.kb_id))
        require_non_empty("doc_id", self.doc_id)
        require_non_empty("chunk_id", self.chunk_id)
        require_non_empty("text", self.text)
        require_non_empty("data_type", self.data_type)
        validate_visibility(self.visibility)
        require_non_empty("chunker_version", self.chunker_version)
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")


@dataclass(frozen=True, slots=True)
class BaseChunkPayload:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    chunk_id: str
    chunk_index: int
    text: str
    data_type: str = "document"
    visibility: str = Visibility.PRIVATE
    content_hash: str = ""
    embedding_version: str = ""
    chunker_version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_chunk(cls, chunk: BaseChunk) -> "BaseChunkPayload":
        return cls(
            project_id=chunk.project_id,
            user_id=chunk.user_id,
            kb_id=chunk.kb_id,
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            data_type=chunk.data_type,
            visibility=chunk.visibility,
            content_hash=chunk.content_hash,
            embedding_version=chunk.embedding_version,
            chunker_version=chunk.chunker_version,
            metadata=dict(chunk.metadata),
        )

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        object.__setattr__(self, "kb_id", normalize_kb_id(self.kb_id))
        require_non_empty("doc_id", self.doc_id)
        require_non_empty("chunk_id", self.chunk_id)
        require_non_empty("text", self.text)
        require_non_empty("data_type", self.data_type)
        validate_visibility(self.visibility)
        require_non_empty("chunker_version", self.chunker_version)
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")

    def to_qdrant_payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "kb_id": self.kb_id,
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "data_type": self.data_type,
            "visibility": str(self.visibility),
            "content_hash": self.content_hash,
            "embedding_version": self.embedding_version,
            "chunker_version": self.chunker_version,
            "metadata": dict(self.metadata),
        }
