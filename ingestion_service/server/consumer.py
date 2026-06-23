"""Queue consumer for ingestion request messages.

Receives queued ingest requests, acknowledges them immediately, and
processes each request asynchronously. This keeps the manager's
response path fast while the actual ingestion work happens in the
background (durable job status can be polled separately).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ingestion_service.jobs import IngestionJobRepository
from ingestion_service.schemas import IngestionJob
from ingestion_service.service import IngestionResult, IngestionService
from shared.contracts import IngestError, IngestResponseEnvelope, JobStatus, QueuedIngestCommand
from shared.queue import QueueBroker, QueueMessage

logger = logging.getLogger(__name__)


class IngestionRequestConsumer:
    """Consumes queued ingest requests and publishes prepared chunks for indexing."""

    def __init__(
        self,
        *,
        queue: QueueBroker,
        jobs: IngestionJobRepository,
        ingestion_service: IngestionService,
        retrieval_queue: QueueBroker,
        retrieval_index_topic: str = "retrieval.index.requests",
        retrieval_index_response_timeout: float = 30.0,
        topic: str = "ingestion.requests",
    ) -> None:
        self._queue = queue
        self._jobs = jobs
        self._ingestion_service = ingestion_service
        self._retrieval_queue = retrieval_queue
        self._retrieval_index_topic = retrieval_index_topic
        self._retrieval_index_response_timeout = retrieval_index_response_timeout
        self._topic = topic
        self._task: asyncio.Task[None] | None = None
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    @property
    def topic(self) -> str:
        return self._topic

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        tasks: list[asyncio.Task[None]] = [self._task]
        if self._inflight_tasks:
            for task in self._inflight_tasks:
                task.cancel()
            tasks.extend(self._inflight_tasks)
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        self._inflight_tasks.clear()

    async def _run(self) -> None:
        while True:
            try:
                message = await self._queue.consume(self._topic)
            except asyncio.CancelledError:
                return

            self._queue.task_done(self._topic)
            task = asyncio.create_task(self._process_message(message))
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

    async def _process_message(self, message: QueueMessage) -> None:
        """Run the actual ingest work asynchronously after ack."""
        command = QueuedIngestCommand.from_queue_payload(
            message.payload,
            fallback_request_id=message.key,
        )
        request_id = command.request_id
        try:
            accepted_job_id = await self._accept_job(command)
            await self._update_job_status(command.request_id, JobStatus.RUNNING)
            prepared = await self._prepare_job(command)
            index_result = await self._publish_index_request(command, prepared)
            await self._update_job_metadata(
                command.request_id,
                _index_result_metadata(index_result),
            )
            await self._update_job_status(command.request_id, JobStatus.COMPLETED)
            result = _indexed_result_payload(command, index_result)
            await self._publish_response(
                message,
                ok=True,
                result=_accepted_result_payload(
                    command,
                    result,
                    accepted_job_id=accepted_job_id,
                ),
            )
            logger.debug(
                "queued ingest completed: request_id=%s job_id=%s",
                request_id,
                getattr(result, "job_id", ""),
            )
        except Exception as exc:
            logger.exception("queued ingest failed: request_id=%s", request_id)
            await self._update_job_status(
                command.request_id,
                JobStatus.FAILED,
                error=str(exc),
            )
            await self._publish_response(
                message,
                ok=False,
                error=_classify_error(exc),
            )

    async def _accept_job(self, command: QueuedIngestCommand) -> str | None:
        await self._jobs.create(
            IngestionJob(
                job_id=command.request_id,
                source_uri=command.source_uri,
                document_id=command.doc_id,
                metadata=command.job_metadata(),
            )
        )
        return command.request_id

    async def _prepare_job(self, command: QueuedIngestCommand) -> IngestionResult:
        result = await self._ingestion_service.process(command.request_payload())
        await self._jobs.update_metadata(
            command.request_id,
            _preparation_metadata(result),
        )
        return result

    async def _publish_index_request(
        self,
        command: QueuedIngestCommand,
        prepared: IngestionResult,
    ) -> dict[str, Any]:
        payload = _index_request_payload(command, prepared)
        response_topic = f"{self._retrieval_index_topic}.responses.{command.request_id}"
        payload["response_topic"] = response_topic
        await self._retrieval_queue.publish(
            QueueMessage(
                topic=self._retrieval_index_topic,
                key=command.request_id,
                payload=payload,
                headers={"correlation_id": command.request_id},
            )
        )
        response = await asyncio.wait_for(
            self._retrieval_queue.consume(response_topic),
            timeout=self._retrieval_index_response_timeout,
        )
        self._retrieval_queue.task_done(response_topic)
        if response.payload.get("ok") is True:
            result = response.payload.get("result")
            return dict(result) if isinstance(result, dict) else {}
        error = response.payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "retrieval indexing failed")
            error_type = str(error.get("type") or "")
            if error_type:
                message = f"{error_type}: {message}"
            raise RuntimeError(message)
        raise RuntimeError("retrieval indexing failed")

    async def _update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> None:
        await self._jobs.update_status(job_id, status, error=error)

    async def _update_job_metadata(
        self,
        job_id: str,
        metadata: dict[str, object],
    ) -> None:
        await self._jobs.update_metadata(job_id, metadata)

    async def _publish_response(
        self,
        message: Any,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        error: IngestError | None = None,
    ) -> None:
        response_topic = str(
            message.payload.get("response_topic", f"{self._topic}.responses.{message.key}")
        )
        request_id = str(message.payload.get("request_id", message.key))
        envelope = IngestResponseEnvelope(
            request_id=request_id,
            ok=ok,
            result=_ingest_job_result_from_dict(result) if result else None,
            error=error,
        )
        await self._queue.publish(
            QueueMessage(
                topic=response_topic,
                key=str(message.key),
                payload=_envelope_to_dict(envelope),
                headers={
                    "correlation_id": str(message.key),
                    "request_topic": self._topic,
                },
            )
        )


def _classify_error(exc: Exception) -> IngestError:
    exc_name = type(exc).__name__
    if exc_name in ("ValueError", "ValidationError"):
        return IngestError(code="VALIDATION_ERROR", message=str(exc), retryable=False)
    return IngestError(code="INTERNAL_ERROR", message=str(exc), retryable=True)


def _accepted_result_payload(
    command: QueuedIngestCommand,
    result: dict[str, Any],
    *,
    accepted_job_id: str | None,
) -> dict[str, Any]:
    payload = dict(result)
    if accepted_job_id is not None:
        payload["job_id"] = accepted_job_id
    payload.setdefault("status", "pending")
    payload.setdefault("doc_id", command.doc_id)
    payload.setdefault("project_id", command.project_id)
    return payload


def _indexed_result_payload(
    command: QueuedIngestCommand,
    index_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "job_id": command.request_id,
        "status": JobStatus.COMPLETED.value,
        "doc_id": command.doc_id,
        "project_id": command.project_id,
        "indexed_chunk_count": int(index_result.get("chunk_count", 0) or 0),
        "dense_enabled": bool(index_result.get("dense_enabled", False)),
        "sparse_enabled": bool(index_result.get("sparse_enabled", False)),
    }


def _index_result_metadata(index_result: dict[str, Any]) -> dict[str, object]:
    return {
        "indexed_chunk_count": int(index_result.get("chunk_count", 0) or 0),
        "dense_enabled": bool(index_result.get("dense_enabled", False)),
        "sparse_enabled": bool(index_result.get("sparse_enabled", False)),
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


def _index_request_payload(
    command: QueuedIngestCommand,
    result: IngestionResult,
) -> dict[str, Any]:
    collection_name = str(command.metadata.get("collection_name", ""))
    if not collection_name.strip():
        raise ValueError("retrieval index collection_name is required")
    retrieval_config = command.metadata.get("retrieval_config", {})
    placement_plan = command.metadata.get("placement_plan", {})
    chunks = [_chunk_payload(chunk) for chunk in result.chunks]
    return {
        "request_id": command.request_id,
        "job_id": command.request_id,
        "collection_name": collection_name,
        "chunks": chunks,
        "payloads": [_retrieval_payload(chunk) for chunk in chunks],
        "retrieval_config": dict(retrieval_config) if isinstance(retrieval_config, dict) else {},
        "placement_plan": dict(placement_plan) if isinstance(placement_plan, dict) else {},
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


def _retrieval_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    payload = dict(chunk)
    payload["payload_id"] = str(chunk.get("chunk_id", ""))
    payload["embedding_version"] = ""
    return payload


def _ingest_job_result_from_dict(data: dict[str, Any]) -> Any:
    """Convert dict payload to a usable result object.

    Returns the original dict so the manager can construct the shared
    IngestJobResult without importing project_service schemas.
    """
    return data


def _envelope_to_dict(envelope: IngestResponseEnvelope) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": envelope.request_id,
        "ok": envelope.ok,
    }
    if envelope.result is not None:
        result: dict[str, Any] = {}
        if isinstance(envelope.result, dict):
            result = envelope.result
        elif hasattr(envelope.result, "job_id"):
            result = {
                "job_id": getattr(envelope.result, "job_id", ""),
                "status": str(getattr(envelope.result, "status", "")),
                "doc_id": getattr(envelope.result, "doc_id", ""),
                "project_id": getattr(envelope.result, "project_id", ""),
                "error": getattr(envelope.result, "error", ""),
            }
        payload["result"] = result
    if envelope.error is not None:
        payload["error"] = {
            "code": envelope.error.code,
            "message": envelope.error.message,
            "retryable": envelope.error.retryable,
        }
    return payload
