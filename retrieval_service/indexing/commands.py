"""Queue command contracts for retrieval indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas import BaseChunk, BaseChunkPayload
from retrieval_service.indexing.service import IndexChunksRequest


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
            else [BaseChunkPayload.from_chunk(chunk) for chunk in chunks]
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
        metadata=dict(value.get("metadata", {}) or {}),
    )


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise ValueError("index command field must be a list")
