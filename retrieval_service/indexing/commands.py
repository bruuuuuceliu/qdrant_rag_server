"""Queue command contracts for retrieval indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas import BaseChunk, BaseChunkPayload
from retrieval_service.indexing.service import IndexChunksRequest
from retrieval_service.memory.schemas.documents import MemoryChunk, MemoryChunkPayload


@dataclass(frozen=True, slots=True)
class RetrievalIndexCommand:
    """Transport-neutral command for `retrieval.index.requests`."""

    request_id: str
    response_topic: str
    job_id: str
    collection_name: str
    chunks: list[BaseChunk]
    payloads: list[BaseChunkPayload]
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    placement_plan: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> "RetrievalIndexCommand":
        chunks = [_chunk_from_mapping(item) for item in _list(payload.get("chunks"))]
        payload_items = _list(payload.get("payloads"))
        payloads = (
            [_payload_from_mapping(item) for item in payload_items]
            if payload_items
            else [
                _payload_from_mapping(_payload_mapping_from_chunk_mapping(item))
                for item in _list(payload.get("chunks"))
            ]
        )
        collection_name = str(payload.get("collection_name", ""))
        if not collection_name.strip():
            raise ValueError("retrieval index collection_name is required")
        return cls(
            request_id=str(payload.get("request_id") or fallback_request_id),
            response_topic=str(payload.get("response_topic") or ""),
            job_id=str(payload.get("job_id") or payload.get("request_id") or fallback_request_id),
            collection_name=collection_name,
            chunks=chunks,
            payloads=payloads,
            retrieval_config=dict(payload.get("retrieval_config", {}) or {}),
            placement_plan=dict(payload.get("placement_plan", {}) or {}),
        )

    def to_index_request(self) -> IndexChunksRequest:
        return IndexChunksRequest(
            collection_name=self.collection_name,
            chunks=self.chunks,
            payloads=self.payloads,
            retrieval_config=dict(self.retrieval_config),
            job_id=self.job_id,
            placement_plan=dict(self.placement_plan),
        )


@dataclass(frozen=True, slots=True)
class RetrievalMemoryIndexCommand:
    """Memory ingest command preserving the memory payload fields.

    The memory payloads carry ``memory_id``/``owner_id``/``agent_id`` top-level
    (in addition to the shared chunk fields); parsing through the memory schemas
    keeps those keys so ``to_qdrant_payload`` writes them for the isolation
    filter used by ``search_memory``.
    """

    request_id: str
    response_topic: str
    job_id: str
    collection_name: str
    chunks: list[MemoryChunk]
    payloads: list[MemoryChunkPayload]
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    placement_plan: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> "RetrievalMemoryIndexCommand":
        chunks = [_memory_chunk_from_mapping(item) for item in _list(payload.get("chunks"))]
        payload_items = _list(payload.get("payloads"))
        payloads = (
            [_memory_payload_from_mapping(item) for item in payload_items]
            if payload_items
            else [
                _memory_payload_from_mapping(_payload_mapping_from_chunk_mapping(item))
                for item in _list(payload.get("chunks"))
            ]
        )
        collection_name = str(payload.get("collection_name", ""))
        if not collection_name.strip():
            raise ValueError("retrieval memory index collection_name is required")
        return cls(
            request_id=str(payload.get("request_id") or fallback_request_id),
            response_topic=str(payload.get("response_topic") or ""),
            job_id=str(payload.get("job_id") or payload.get("request_id") or fallback_request_id),
            collection_name=collection_name,
            chunks=chunks,
            payloads=payloads,
            retrieval_config=dict(payload.get("retrieval_config", {}) or {}),
            placement_plan=dict(payload.get("placement_plan", {}) or {}),
        )

    def to_index_request(self) -> IndexChunksRequest:
        return IndexChunksRequest(
            collection_name=self.collection_name,
            chunks=self.chunks,
            payloads=self.payloads,
            retrieval_config=dict(self.retrieval_config),
            job_id=self.job_id,
            placement_plan=dict(self.placement_plan),
        )


def _memory_chunk_from_mapping(value: Any) -> MemoryChunk:
    if not isinstance(value, dict):
        raise ValueError("memory chunk must be an object")
    return MemoryChunk(
        chunk_id=str(value.get("chunk_id", "")),
        chunk_index=int(value.get("chunk_index", 0)),
        text=str(value.get("text", "")),
        memory_id=str(value.get("memory_id", "")),
        owner_id=str(value.get("owner_id", "")),
        agent_id=str(value.get("agent_id", "")),
        document_id=str(value.get("document_id", "")),
        data_type=str(value.get("data_type", "memory")),
        memory_type=str(value.get("memory_type", "semantic")),
        content_hash=str(value.get("content_hash", "")),
        chunker_version=str(value.get("chunker_version", "v1")),
        metadata=dict(value.get("metadata", {}) or {}),
    )


def _memory_payload_from_mapping(value: Any) -> MemoryChunkPayload:
    if not isinstance(value, dict):
        raise ValueError("memory payload must be an object")
    chunk_id = str(value.get("chunk_id", ""))
    return MemoryChunkPayload(
        payload_id=str(value.get("payload_id") or chunk_id),
        chunk_id=chunk_id,
        chunk_index=int(value.get("chunk_index", 0)),
        text=str(value.get("text", "")),
        memory_id=str(value.get("memory_id", "")),
        owner_id=str(value.get("owner_id", "")),
        agent_id=str(value.get("agent_id", "")),
        run_id=str(value.get("run_id", "")),
        document_id=str(value.get("document_id", "")),
        data_type=str(value.get("data_type", "memory")),
        memory_type=str(value.get("memory_type", "semantic")),
        content_hash=str(value.get("content_hash", "")),
        embedding_version=str(value.get("embedding_version", "")),
        chunker_version=str(value.get("chunker_version", "v1")),
        metadata=_payload_metadata(value),
    )


def _chunk_from_mapping(value: Any) -> BaseChunk:
    if not isinstance(value, dict):
        raise ValueError("chunk must be an object")
    return BaseChunk(
        document_id=str(value.get("document_id", "")),
        chunk_id=str(value.get("chunk_id", "")),
        chunk_index=int(value.get("chunk_index", 0)),
        text=str(value.get("text", "")),
        data_type=str(value.get("data_type", "document")),
        content_hash=str(value.get("content_hash", "")),
        chunker_version=str(value.get("chunker_version", "v1")),
        metadata=dict(value.get("metadata", {}) or {}),
    )


def _payload_from_mapping(value: Any) -> BaseChunkPayload:
    if not isinstance(value, dict):
        raise ValueError("payload must be an object")
    chunk_id = str(value.get("chunk_id", ""))
    return BaseChunkPayload(
        payload_id=str(value.get("payload_id") or chunk_id),
        document_id=str(value.get("document_id", "")),
        chunk_id=chunk_id,
        chunk_index=int(value.get("chunk_index", 0)),
        text=str(value.get("text", "")),
        data_type=str(value.get("data_type", "document")),
        content_hash=str(value.get("content_hash", "")),
        embedding_version=str(value.get("embedding_version", "")),
        chunker_version=str(value.get("chunker_version", "v1")),
        metadata=_payload_metadata(value),
    )


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise ValueError("index command field must be a list")


def _payload_metadata(value: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(value.get("metadata", {}) or {})
    for key in ("project_id", "user_id", "kb_id", "doc_id"):
        item = value.get(key)
        if item is not None and str(item).strip():
            metadata.setdefault(key, str(item))
    return metadata


def _payload_mapping_from_chunk_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("chunk must be an object")
    payload = dict(value)
    payload["payload_id"] = str(value.get("payload_id") or value.get("chunk_id", ""))
    payload.setdefault("embedding_version", "")
    return payload
