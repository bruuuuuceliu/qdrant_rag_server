"""Transport-neutral ingestion API contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IngestionStatusCommand:
    request_id: str
    job_id: str

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> "IngestionStatusCommand":
        request_payload = _request_payload(payload)
        request_id = str(payload.get("request_id") or fallback_request_id)
        job_id = str(request_payload.get("job_id") or payload.get("job_id") or "")
        if not job_id.strip():
            raise ValueError("ingestion status job_id is required")
        return cls(request_id=request_id, job_id=job_id)


@dataclass(frozen=True, slots=True)
class IngestionApiError:
    code: str
    message: str
    retryable: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class IngestionResponseEnvelope:
    request_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: IngestionApiError | None = None

    @classmethod
    def success(
        cls,
        *,
        request_id: str,
        result: dict[str, Any],
    ) -> "IngestionResponseEnvelope":
        return cls(request_id=request_id, ok=True, result=result)

    @classmethod
    def failure(
        cls,
        *,
        request_id: str,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> "IngestionResponseEnvelope":
        return cls(
            request_id=request_id,
            ok=False,
            error=IngestionApiError(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"request_id": self.request_id, "ok": self.ok}
        if self.result is not None:
            payload["result"] = dict(self.result)
        if self.error is not None:
            payload["error"] = self.error.to_mapping()
        return payload


def job_to_mapping(job: Any) -> dict[str, Any]:
    metadata = dict(getattr(job, "metadata", {}) or {})
    return {
        "job_id": str(getattr(job, "job_id", "")),
        "status": str(getattr(job, "status", "")),
        "doc_id": str(getattr(job, "document_id", "")),
        "source_uri": str(getattr(job, "source_uri", "")),
        "error": getattr(job, "error", None),
        "metadata": metadata,
        "created_at": float(getattr(job, "created_at", 0.0) or 0.0),
        "updated_at": float(getattr(job, "updated_at", 0.0) or 0.0),
    }


def _request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    if request is None:
        return payload
    if not isinstance(request, dict):
        raise ValueError("ingestion API request must be an object")
    return dict(request)
