"""Broker-command ingestion runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ingestion_service.jobs import IngestionJobRepository
from ingestion_service.schemas import IngestionJob
from ingestion_service.storage import make_raw_storage_key
from ingestion_service.service import IngestionResult, IngestionService
from shared.contracts import DataType, JobStatus, normalize_data_type


@dataclass(frozen=True, slots=True)
class IngestionPlan:
    """Ingestion-helper-owned plan parsed from a task-service helper command."""

    request_id: str
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    source_uri: str
    content_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_text: str | None = None
    raw_content: Any | None = None

    @classmethod
    def from_plan(cls, plan: dict[str, Any]) -> "IngestionPlan":
        payload = _command_plan(plan)
        metadata = _metadata(payload.get("metadata", {}))
        data_type = normalize_data_type(metadata.get("data_type"))
        metadata["data_type"] = str(data_type)
        return cls(
            request_id=str(payload.get("request_id") or payload.get("job_id") or ""),
            project_id=str(payload.get("project_id", "")),
            user_id=str(payload.get("user_id", "")),
            kb_id=str(payload.get("kb_id", "")),
            doc_id=str(payload.get("doc_id", "")),
            source_uri=str(payload.get("source_uri", "")),
            content_type=str(payload.get("content_type", "")),
            metadata=metadata,
            raw_text=_optional_str(payload.get("raw_text")),
            raw_content=payload.get("raw_content"),
        )

    def request_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "kb_id": self.kb_id,
            "doc_id": self.doc_id,
            "source_uri": self.source_uri,
            "content_type": self.content_type,
            "metadata": dict(self.metadata),
        }
        if self.raw_text is not None:
            payload["raw_text"] = self.raw_text
        if self.raw_content is not None:
            payload["raw_content"] = self.raw_content
        return payload

    def job_metadata(self) -> dict[str, Any]:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "project_id": self.project_id,
                "user_id": self.user_id,
                "kb_id": self.kb_id,
                "doc_id": self.doc_id,
                "data_type": str(metadata.get("data_type") or DataType.PROJECT_DOCUMENT),
                "content_type": self.content_type,
                "request_id": self.request_id,
            }
        )
        return metadata


class BrokerIngestionApp:
    """Runs one ingestion command and returns the retrieval-index plan."""

    def __init__(
        self,
        *,
        jobs: IngestionJobRepository,
        ingestion_service: IngestionService,
    ) -> None:
        self.jobs = jobs
        self._ingestion_service = ingestion_service

    async def start_ingest(self, plan: dict[str, Any]) -> dict[str, Any]:
        command = IngestionPlan.from_plan(plan)
        try:
            await self.jobs.create(
                IngestionJob(
                    job_id=command.request_id,
                    source_uri=command.source_uri,
                    document_id=command.doc_id,
                    metadata=command.job_metadata(),
                )
            )
            await self.jobs.update_status(command.request_id, JobStatus.RUNNING)
            prepared = await self._ingestion_service.process(command.request_payload())
            await self.jobs.update_metadata(command.request_id, _preparation_metadata(prepared))
            index_request = _index_request_payload(command, prepared)
            return {
                "ok": True,
                "job_id": command.request_id,
                "status": JobStatus.RUNNING.value,
                "doc_id": command.doc_id,
                "project_id": command.project_id,
                "index_request": index_request,
                "storage_request": _storage_request(command, prepared.raw_content),
            }
        except Exception as exc:
            await self.jobs.update_status(
                command.request_id,
                JobStatus.FAILED,
                error=str(exc),
            )
            return {
                "ok": False,
                "job_id": command.request_id,
                "status": JobStatus.FAILED.value,
                "doc_id": command.doc_id,
                "project_id": command.project_id,
                "error": str(exc),
            }


def _storage_request(command: IngestionPlan, raw_content: bytes) -> dict[str, Any]:
    key = make_raw_storage_key(command.project_id, command.user_id, command.doc_id)
    return {
        "operation": "put",
        "key": key,
        "value": raw_content.decode("utf-8", errors="replace"),
    }


def _command_plan(plan: dict[str, Any]) -> dict[str, Any]:
    payload = dict(plan)
    metadata = dict(payload.get("metadata", {}) or {})
    for key in ("collection_name", "retrieval_config", "placement_plan", "chunker_config"):
        if key in payload:
            metadata[key] = payload[key]
    payload["metadata"] = metadata
    return payload


def _index_request_payload(
    command: IngestionPlan,
    result: IngestionResult,
) -> dict[str, Any]:
    collection_name = str(command.metadata.get("collection_name", ""))
    if not collection_name.strip():
        raise ValueError("retrieval index collection_name is required")
    retrieval_config = command.metadata.get("retrieval_config", {})
    placement_plan = command.metadata.get("placement_plan", {})
    chunks = [_chunk_payload(chunk) for chunk in result.chunks]
    scope = {
        "project_id": command.project_id,
        "user_id": command.user_id,
        "kb_id": command.kb_id,
        "doc_id": command.doc_id,
    }
    return {
        "request_id": command.request_id,
        "job_id": command.request_id,
        "collection_name": collection_name,
        "chunks": chunks,
        "payloads": [_retrieval_payload(chunk, scope=scope) for chunk in chunks],
        "retrieval_config": dict(retrieval_config) if isinstance(retrieval_config, dict) else {},
        "placement_plan": dict(placement_plan) if isinstance(placement_plan, dict) else {},
    }


def _preparation_metadata(result: IngestionResult) -> dict[str, Any]:
    chunker_versions = sorted({chunk.chunker_version for chunk in result.chunks})
    return {
        "content_hash": result.document.content_hash or result.source.checksum,
        "prepared_chunk_count": len(result.chunks),
        "raw_content_length": len(result.raw_content),
        "handler_name": result.route_decision.handler_name,
        "content_type": result.document.content_type or result.source.content_type,
        "chunker_versions": chunker_versions,
    }


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    return {
        "document_id": str(getattr(chunk, "document_id", "")),
        "chunk_id": str(getattr(chunk, "chunk_id", "")),
        "chunk_index": int(getattr(chunk, "chunk_index", 0)),
        "text": str(getattr(chunk, "text", "")),
        "data_type": str(getattr(chunk, "data_type", "document")),
        "content_hash": str(getattr(chunk, "content_hash", "")),
        "chunker_version": str(getattr(chunk, "chunker_version", "v1")),
        "metadata": dict(getattr(chunk, "metadata", {}) or {}),
    }


def _retrieval_payload(
    chunk: dict[str, Any],
    *,
    scope: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = dict(chunk)
    payload["payload_id"] = str(chunk.get("chunk_id", ""))
    payload["embedding_version"] = ""
    if scope is not None:
        for key, value in scope.items():
            if value:
                payload[key] = value
    return payload


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
