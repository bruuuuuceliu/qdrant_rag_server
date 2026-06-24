"""Broker-command ingestion runtime."""

from __future__ import annotations

from typing import Any

from ingestion_service.jobs import IngestionJobRepository
from ingestion_service.schemas import IngestionJob
from ingestion_service.storage import make_raw_storage_key
from ingestion_service.server.consumer import _index_request_payload, _preparation_metadata
from ingestion_service.service import IngestionService
from shared.contracts import JobStatus, QueuedIngestCommand


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
        command = QueuedIngestCommand.from_queue_payload(
            _command_plan(plan),
            fallback_request_id=str(plan.get("request_id") or plan.get("job_id") or ""),
        )
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


def _storage_request(command: QueuedIngestCommand, raw_content: bytes) -> dict[str, Any]:
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
