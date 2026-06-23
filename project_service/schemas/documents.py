"""Project-RAG document, chunk, and payload schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from project_service.schemas.common import (
    Visibility,
    normalize_kb_id,
    require_non_empty,
    validate_visibility,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectDocument:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    document_id: str = ""
    source_uri: str = ""
    content_type: str = "text/plain"
    data_type: str = "project_document"
    content_hash: str = ""
    visibility: str = Visibility.PRIVATE
    embedding_version: str = ""
    chunker_version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", self.document_id or self.doc_id)
        object.__setattr__(self, "kb_id", normalize_kb_id(self.kb_id))
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        require_non_empty("doc_id", self.doc_id)
        require_non_empty("document_id", self.document_id)
        require_non_empty("source_uri", self.source_uri)
        require_non_empty("content_type", self.content_type)
        require_non_empty("data_type", self.data_type)
        validate_visibility(self.visibility)
        require_non_empty("chunker_version", self.chunker_version)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectChunk:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    chunk_id: str
    chunk_index: int
    text: str
    document_id: str = ""
    data_type: str = "project_document"
    content_hash: str = ""
    chunker_version: str = "v1"
    visibility: str = Visibility.PRIVATE
    embedding_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", self.document_id or self.doc_id)
        object.__setattr__(self, "kb_id", normalize_kb_id(self.kb_id))
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        require_non_empty("doc_id", self.doc_id)
        require_non_empty("document_id", self.document_id)
        require_non_empty("chunk_id", self.chunk_id)
        require_non_empty("text", self.text)
        require_non_empty("data_type", self.data_type)
        require_non_empty("chunker_version", self.chunker_version)
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")
        validate_visibility(self.visibility)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectChunkPayload:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    chunk_id: str
    chunk_index: int
    text: str
    payload_id: str = ""
    document_id: str = ""
    data_type: str = "project_document"
    content_hash: str = ""
    embedding_version: str = ""
    chunker_version: str = "v1"
    visibility: str = Visibility.PRIVATE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_chunk(cls, chunk: ProjectChunk) -> "ProjectChunkPayload":
        return cls(
            payload_id=chunk.chunk_id,
            project_id=chunk.project_id,
            user_id=chunk.user_id,
            kb_id=chunk.kb_id,
            doc_id=chunk.doc_id,
            document_id=chunk.document_id,
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
        object.__setattr__(self, "document_id", self.document_id or self.doc_id)
        object.__setattr__(self, "payload_id", self.payload_id or self.chunk_id)
        object.__setattr__(self, "kb_id", normalize_kb_id(self.kb_id))
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        require_non_empty("doc_id", self.doc_id)
        require_non_empty("document_id", self.document_id)
        require_non_empty("payload_id", self.payload_id)
        require_non_empty("chunk_id", self.chunk_id)
        require_non_empty("text", self.text)
        require_non_empty("data_type", self.data_type)
        require_non_empty("chunker_version", self.chunker_version)
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")
        validate_visibility(self.visibility)

    def point_identity(self) -> tuple[str, ...]:
        return (
            self.project_id,
            self.user_id,
            self.kb_id,
            self.doc_id,
            self.data_type,
            str(self.chunk_index),
            self.chunker_version,
        )

    def to_qdrant_payload(self) -> dict[str, Any]:
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
            "project_id": self.project_id,
            "user_id": self.user_id,
            "kb_id": self.kb_id,
            "doc_id": self.doc_id,
            "visibility": str(self.visibility),
        }
