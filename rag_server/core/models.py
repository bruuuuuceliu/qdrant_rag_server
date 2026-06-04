"""Reusable base models for the project-based RAG engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


SHARED_USER_ID = "__shared__"


class IngestJobStatus(StrEnum):
    """Lifecycle states for asynchronous document ingestion."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BaseProjectConfig:
    project_id: str
    project_type: str
    active_embedding_version: str
    embedding_model: str
    reranker_model: str
    chunker_config: dict[str, Any] = field(default_factory=dict)
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    cache_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty("project_id", self.project_id)
        _require_non_empty("project_type", self.project_type)
        _require_non_empty("active_embedding_version", self.active_embedding_version)
        _require_non_empty("embedding_model", self.embedding_model)
        _require_non_empty("reranker_model", self.reranker_model)

    @property
    def collection_name(self) -> str:
        return f"rag_{self.project_id}_{self.active_embedding_version}"


@dataclass(frozen=True, slots=True)
class BaseQueryScope:
    project_id: str
    user_id: str
    kb_ids: tuple[str, ...] = ()
    include_shared: bool = True

    def __post_init__(self) -> None:
        _require_non_empty("project_id", self.project_id)
        _require_non_empty("user_id", self.user_id)
        object.__setattr__(self, "kb_ids", tuple(self.kb_ids))


@dataclass(frozen=True, slots=True)
class BaseRetrievalFilter:
    project_id: str
    user_id: str
    kb_ids: tuple[str, ...] = ()
    doc_ids: tuple[str, ...] = ()
    shared_user_id: str | None = SHARED_USER_ID

    def __post_init__(self) -> None:
        _require_non_empty("project_id", self.project_id)
        _require_non_empty("user_id", self.user_id)
        object.__setattr__(self, "kb_ids", tuple(self.kb_ids))
        object.__setattr__(self, "doc_ids", tuple(self.doc_ids))

    @classmethod
    def from_scope(
        cls,
        scope: BaseQueryScope,
        *,
        doc_ids: tuple[str, ...] = (),
        shared_user_id: str = SHARED_USER_ID,
    ) -> BaseRetrievalFilter:
        return cls(
            project_id=scope.project_id,
            user_id=scope.user_id,
            kb_ids=scope.kb_ids,
            doc_ids=doc_ids,
            shared_user_id=shared_user_id if scope.include_shared else None,
        )

    @property
    def allowed_user_ids(self) -> tuple[str, ...]:
        if self.shared_user_id is None:
            return (self.user_id,)
        return (self.user_id, self.shared_user_id)


@dataclass(frozen=True, slots=True)
class BaseDocument:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    source_uri: str
    content_type: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty("project_id", self.project_id)
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("kb_id", self.kb_id)
        _require_non_empty("doc_id", self.doc_id)
        _require_non_empty("source_uri", self.source_uri)
        _require_non_empty("content_type", self.content_type)


@dataclass(frozen=True, slots=True)
class BaseChunk:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    chunk_id: str
    chunk_index: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty("project_id", self.project_id)
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("kb_id", self.kb_id)
        _require_non_empty("doc_id", self.doc_id)
        _require_non_empty("chunk_id", self.chunk_id)
        _require_non_empty("text", self.text)
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
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_chunk(cls, chunk: BaseChunk) -> BaseChunkPayload:
        return cls(
            project_id=chunk.project_id,
            user_id=chunk.user_id,
            kb_id=chunk.kb_id,
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            metadata=dict(chunk.metadata),
        )

    def __post_init__(self) -> None:
        _require_non_empty("project_id", self.project_id)
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("kb_id", self.kb_id)
        _require_non_empty("doc_id", self.doc_id)
        _require_non_empty("chunk_id", self.chunk_id)
        _require_non_empty("text", self.text)
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
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class BaseIngestJob:
    project_id: str
    user_id: str
    doc_id: str
    source_uri: str
    status: IngestJobStatus = IngestJobStatus.PENDING
    error: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("project_id", self.project_id)
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("doc_id", self.doc_id)
        _require_non_empty("source_uri", self.source_uri)


@dataclass(frozen=True, slots=True)
class BaseCacheScope:
    project_id: str
    user_id: str
    query_hash: str
    config_version: str

    def __post_init__(self) -> None:
        _require_non_empty("project_id", self.project_id)
        _require_non_empty("user_id", self.user_id)
        _require_non_empty("query_hash", self.query_hash)
        _require_non_empty("config_version", self.config_version)


def _require_non_empty(field_name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")
