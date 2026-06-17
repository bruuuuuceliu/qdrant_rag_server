"""Transport-neutral ingest queue contract types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.contracts.data_types import DataType, normalize_data_type

from shared.contracts.jobs import JobStatus


@dataclass(frozen=True, slots=True)
class QueuedIngestCommand:
    """Transport-neutral command carried on the ingestion request queue."""

    request_id: str
    response_topic: str
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
    def from_queue_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> "QueuedIngestCommand":
        request = payload.get("request")
        request_payload = request if isinstance(request, dict) else payload
        metadata = _metadata(request_payload.get("metadata", {}))
        data_type = normalize_data_type(metadata.get("data_type"))
        metadata["data_type"] = str(data_type)
        return cls(
            request_id=str(payload.get("request_id") or fallback_request_id),
            response_topic=str(payload.get("response_topic") or ""),
            project_id=str(request_payload.get("project_id", "")),
            user_id=str(request_payload.get("user_id", "")),
            kb_id=str(request_payload.get("kb_id", "")),
            doc_id=str(request_payload.get("doc_id", "")),
            source_uri=str(request_payload.get("source_uri", "")),
            content_type=str(request_payload.get("content_type", "")),
            metadata=metadata,
            raw_text=_optional_str(request_payload.get("raw_text")),
            raw_content=request_payload.get("raw_content"),
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


@dataclass
class IngestError:
    """Structured error carried inside an ingest response envelope."""

    code: str
    message: str
    retryable: bool = False


@dataclass
class IngestResponseEnvelope:
    """Typed envelope for queued ingest request/response communication.

    Carries a shared contract that both manager and ingestion service agree on.
    """

    request_id: str
    ok: bool
    result: IngestJobResult | None = None
    error: IngestError | None = None


@dataclass
class IngestJobResult:
    """Transport-neutral ingest result returned through the queue boundary.

    This is intentionally slim so that service-to-service communication does
    not depend on internal domain models from project_service or retrieval_service.
    """

    job_id: str
    status: JobStatus
    doc_id: str = ""
    project_id: str = ""
    error: str = ""


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
