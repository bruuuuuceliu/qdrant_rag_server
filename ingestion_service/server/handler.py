"""Ingestion API payload handler."""

from __future__ import annotations

from typing import Any

from ingestion_service.server.contracts import (
    IngestionResponseEnvelope,
    IngestionStatusCommand,
    job_to_mapping,
)


class IngestionApiHandler:
    """Dispatches transport-neutral ingestion API payloads."""

    def __init__(self, *, app: Any) -> None:
        self._app = app

    async def get_status(
        self,
        payload: dict[str, Any],
        *,
        fallback_request_id: str = "ingestion-status",
    ) -> dict[str, Any]:
        request_id = str(payload.get("request_id") or fallback_request_id)
        try:
            command = IngestionStatusCommand.from_payload(
                payload,
                fallback_request_id=fallback_request_id,
            )
            jobs = getattr(self._app, "jobs", None)
            if jobs is None:
                return IngestionResponseEnvelope.failure(
                    request_id=command.request_id,
                    code="unavailable",
                    message="ingestion job storage is not configured",
                    retryable=True,
                ).to_mapping()
            job = await jobs.get(command.job_id)
            if job is None:
                return IngestionResponseEnvelope.failure(
                    request_id=command.request_id,
                    code="not_found",
                    message=f"ingestion job not found: {command.job_id}",
                    retryable=False,
                ).to_mapping()
            return IngestionResponseEnvelope.success(
                request_id=command.request_id,
                result={"job": job_to_mapping(job)},
            ).to_mapping()
        except ValueError as exc:
            return IngestionResponseEnvelope.failure(
                request_id=request_id,
                code="validation_error",
                message=str(exc),
                retryable=False,
            ).to_mapping()
        except Exception as exc:
            return IngestionResponseEnvelope.failure(
                request_id=request_id,
                code="internal_error",
                message=str(exc) or "ingestion status request failed",
                retryable=True,
            ).to_mapping()

    async def health(
        self,
        payload: dict[str, Any] | None = None,
        *,
        fallback_request_id: str = "ingestion-health",
    ) -> dict[str, Any]:
        payload = payload or {}
        request_id = str(payload.get("request_id") or fallback_request_id)
        return IngestionResponseEnvelope.success(
            request_id=request_id,
            result={
                "enabled": bool(getattr(self._app, "enabled", False)),
                "topic": str(getattr(self._app, "topic", "")),
                "jobs_configured": getattr(self._app, "jobs", None) is not None,
                "consumer_running": getattr(self._app, "consumer", None) is not None,
            },
        ).to_mapping()
