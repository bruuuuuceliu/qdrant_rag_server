"""Thin manager facade over service-client boundaries."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from manager_service.clients import ProjectDocumentClient
from manager_service.errors import ManagerIngestFailedError, ManagerIngestTimeoutError
from manager_service.routing import DataType, ManagerRouter, Operation, RouteRequest
from shared.queue import QueueMessage


class ManagerService:
    """Coordinates public operations while service extraction is in progress."""

    def __init__(
        self,
        *,
        project_documents: ProjectDocumentClient,
        ingest_queue: Any | None = None,
        ingest_topic: str = "ingestion.requests",
        ingest_response_timeout: float = 30.0,
        router: ManagerRouter | None = None,
    ) -> None:
        self._project_documents = project_documents
        self._ingest_queue = ingest_queue
        self._ingest_topic = ingest_topic
        self._ingest_response_timeout = ingest_response_timeout
        self._router = router or ManagerRouter()

    async def ingest(self, request: Any) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.INGEST,
                data_type=_data_type(request),
                project_id=_request_str(request, "project_id"),
                user_id=_request_str(request, "user_id"),
                kb_id=_request_str(request, "kb_id"),
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        if self._ingest_queue is None:
            return await self._project_documents.ingest(request)
        return await self._queue_ingest(request)

    async def search(self, request: Any) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.SEARCH,
                data_type=_data_type(request),
                project_id=_request_str(request, "project_id"),
                user_id=_request_str(request, "user_id"),
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        return await self._project_documents.search(request)

    async def ingest_status(
        self,
        job_id: str,
        *,
        data_type: str = DataType.PROJECT_DOCUMENT,
    ) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.STATUS,
                data_type=data_type,
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        return await self._project_documents.ingest_status(job_id)

    async def delete(self, request: Any) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.DELETE,
                data_type=_data_type(request),
                project_id=_request_str(request, "project_id"),
                user_id=_request_str(request, "user_id"),
                kb_id=_request_str(request, "kb_id"),
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        return await self._project_documents.delete_document(request)

    async def _queue_ingest(self, request: Any) -> Any:
        request_id = str(uuid.uuid4())
        response_topic = f"{self._ingest_topic}.responses.{request_id}"
        await self._ingest_queue.publish(
            QueueMessage(
                topic=self._ingest_topic,
                key=request_id,
                payload={
                    "request_id": request_id,
                    "response_topic": response_topic,
                    "request": _ingest_request_payload(request),
                },
                headers={"correlation_id": request_id},
            )
        )
        try:
            response = await asyncio.wait_for(
                self._ingest_queue.consume(response_topic),
                timeout=self._ingest_response_timeout,
            )
        except TimeoutError as exc:
            raise ManagerIngestTimeoutError(
                request_id=request_id,
                timeout=self._ingest_response_timeout,
            ) from exc
        task_done = getattr(self._ingest_queue, "task_done", None)
        if task_done is not None:
            task_done(response_topic)
        if response.payload.get("ok"):
            return _ingest_result_from_payload(response.payload.get("result"))
        raise ManagerIngestFailedError(
            str(response.payload.get("error", "ingest failed")),
            request_id=request_id,
        )


def _data_type(request: Any) -> str:
    if isinstance(request, dict):
        metadata = request.get("metadata", {})
    else:
        metadata = getattr(request, "metadata", {})
    metadata = metadata or {}
    value = metadata.get("data_type") if isinstance(metadata, dict) else None
    return str(value or DataType.PROJECT_DOCUMENT)


def _request_str(request: Any, field: str) -> str:
    if isinstance(request, dict):
        return str(request.get(field, ""))
    return str(getattr(request, field, ""))


def _ingest_request_payload(request: Any) -> dict[str, Any]:
    if isinstance(request, dict):
        return dict(request)
    return {
        "project_id": str(getattr(request, "project_id", "")),
        "user_id": str(getattr(request, "user_id", "")),
        "kb_id": str(getattr(request, "kb_id", "")),
        "doc_id": str(getattr(request, "doc_id", "")),
        "source_uri": str(getattr(request, "source_uri", "")),
        "content_type": str(getattr(request, "content_type", "")),
        "metadata": dict(getattr(request, "metadata", {}) or {}),
    }


def _ingest_result_from_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    from project_service.schemas import IngestResult
    from retrieval_service.core.schemas import JobStatus

    data = dict(payload)
    if "status" in data:
        data["status"] = JobStatus(data["status"])
    return IngestResult(**data)
