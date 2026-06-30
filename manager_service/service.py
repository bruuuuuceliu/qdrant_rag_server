"""Thin manager facade over the project-service task boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any
from uuid import uuid4

from manager_service.routing import DataType, ManagerRouter, Operation, RouteRequest
from shared.contracts import MessageEnvelope, MessageProducer, MessageType, TOPICS, TaskIntakePayload
from shared.contracts import TaskStatusStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ManagerTaskAccepted:
    task_id: str
    correlation_id: str
    accepted: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True, slots=True)
class ManagerRequestContext:
    """Auth/customer context forwarded by manager without owning policy."""

    request_id: str = ""
    auth_context: dict[str, Any] = field(default_factory=dict)
    customer_context: dict[str, Any] = field(default_factory=dict)
    placement_hint: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "auth_context": dict(self.auth_context),
            "customer_context": dict(self.customer_context),
            "placement_hint": dict(self.placement_hint),
        }


class ManagerService:
    """Coordinates public operations through service-owned boundaries."""

    def __init__(
        self,
        *,
        task_producer: MessageProducer | None = None,
        task_status_store: TaskStatusStore | None = None,
        task_intake_topic: str = TOPICS.task_intake,
        router: ManagerRouter | None = None,
    ) -> None:
        if task_producer is None:
            raise ValueError("ManagerService requires a task producer for broker-first runtime")
        self._task_producer = task_producer
        self._task_status_store = task_status_store
        self._task_intake_topic = task_intake_topic
        self._router = router or ManagerRouter()

    async def ingest(
        self,
        request: Any,
        *,
        context: ManagerRequestContext | None = None,
    ) -> Any:
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
        return await self._publish_task(Operation.INGEST, request, context=context)

    async def search(
        self,
        request: Any,
        *,
        context: ManagerRequestContext | None = None,
    ) -> Any:
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
        return await self._publish_task(Operation.SEARCH, request, context=context)

    async def ingest_status(
        self,
        job_id: str,
        *,
        data_type: str = DataType.PROJECT_DOCUMENT,
        context: ManagerRequestContext | None = None,
    ) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.STATUS,
                data_type=data_type,
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        if self._task_status_store is not None:
            return await self._task_status_store.get_status(job_id)
        raise ValueError("task status lookup is not configured")

    async def delete(
        self,
        request: Any,
        *,
        context: ManagerRequestContext | None = None,
    ) -> Any:
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
        return await self._publish_task(Operation.DELETE, request, context=context)

    async def _publish_task(
        self,
        operation: Operation,
        request: Any,
        *,
        context: ManagerRequestContext | None = None,
    ) -> ManagerTaskAccepted:
        if self._task_producer is None:
            raise ValueError("task producer is not configured")
        correlation_id = context.request_id if context and context.request_id else uuid4().hex
        task_id = _request_task_id(request) or uuid4().hex
        request_payload = _request_payload(request)
        context_payload = context.to_payload() if context is not None else {}
        data_type = _data_type(request)
        envelope = MessageEnvelope.create(
            producer="manager_service",
            message_type=MessageType.REQUEST_ACCEPTED,
            data_type=data_type,
            task_id=task_id,
            correlation_id=correlation_id,
            payload=TaskIntakePayload(
                operation=operation.value,
                request=request_payload,
                context=context_payload,
            ).to_payload(),
        )
        await self._task_producer.publish(self._task_intake_topic, envelope, key=task_id)
        await self._publish_manager_request_accepted(
            operation=operation,
            request=request_payload,
            context=context_payload,
            data_type=data_type,
            task_id=task_id,
            correlation_id=correlation_id,
            source_message_id=envelope.message_id,
        )
        await self._publish_audit_event(
            operation=operation,
            request=request_payload,
            context=context_payload,
            data_type=data_type,
            task_id=task_id,
            correlation_id=correlation_id,
            source_message_id=envelope.message_id,
        )
        logger.info(
            "manager accepted task task_id=%s correlation_id=%s operation=%s data_type=%s topic=%s",
            task_id,
            correlation_id,
            operation.value,
            envelope.data_type,
            self._task_intake_topic,
        )
        return ManagerTaskAccepted(task_id=task_id, correlation_id=correlation_id)

    async def _publish_manager_request_accepted(
        self,
        *,
        operation: Operation,
        request: dict[str, Any],
        context: dict[str, Any],
        data_type: str,
        task_id: str,
        correlation_id: str,
        source_message_id: str,
    ) -> None:
        if self._task_producer is None:
            raise ValueError("task producer is not configured")
        event = MessageEnvelope.create(
            producer="manager_service",
            message_type=MessageType.REQUEST_ACCEPTED,
            data_type=data_type,
            task_id=task_id,
            correlation_id=correlation_id,
            payload={
                "operation": operation.value,
                "status": "accepted",
                "request": _request_summary(request),
                "context": _context_summary(context),
                "source_message_id": source_message_id,
            },
        )
        await self._task_producer.publish(TOPICS.manager_request_accepted, event, key=task_id)

    async def _publish_audit_event(
        self,
        *,
        operation: Operation,
        request: dict[str, Any],
        context: dict[str, Any],
        data_type: str,
        task_id: str,
        correlation_id: str,
        source_message_id: str,
    ) -> None:
        if self._task_producer is None:
            raise ValueError("task producer is not configured")
        request_summary = _request_summary(request)
        event = MessageEnvelope.create(
            producer="manager_service",
            message_type=MessageType.AUDIT_EVENT,
            data_type=data_type,
            task_id=task_id,
            correlation_id=correlation_id,
            payload={
                "event": "manager.request.accepted",
                "operation": operation.value,
                "status": "accepted",
                "job_id": task_id,
                "project_id": request_summary.get("project_id", ""),
                "user_id": request_summary.get("user_id", ""),
                "kb_id": request_summary.get("kb_id", ""),
                "doc_id": request_summary.get("doc_id", ""),
                "data_type": data_type,
                "request": request_summary,
                "context": _context_summary(context),
                "source_message_id": source_message_id,
            },
        )
        await self._task_producer.publish(TOPICS.audit_events, event, key=task_id)


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


def _request_task_id(request: Any) -> str:
    return _request_str(request, "task_id") or _request_str(request, "job_id")


def _request_payload(request: Any) -> dict[str, Any]:
    if isinstance(request, dict):
        return dict(request)
    if hasattr(request, "to_dict"):
        value = request.to_dict()
        return dict(value) if isinstance(value, dict) else {"value": value}
    if hasattr(request, "__dict__"):
        return dict(vars(request))
    fields = {
        name: getattr(request, name)
        for name in ("project_id", "user_id", "kb_id", "doc_id", "query", "metadata")
        if hasattr(request, name)
    }
    return fields or {"value": str(request)}


def _request_summary(request: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "project_id",
        "user_id",
        "kb_id",
        "doc_id",
        "source_uri",
        "content_type",
        "task_id",
        "job_id",
    )
    summary = {
        field: str(request[field])
        for field in fields
        if request.get(field) is not None and str(request.get(field, "")).strip()
    }
    metadata = request.get("metadata", {})
    if isinstance(metadata, dict):
        data_type = metadata.get("data_type")
        if data_type is not None and str(data_type).strip():
            summary["data_type"] = str(data_type)
    return summary


def _context_summary(context: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for field in ("request_id", "auth_context", "customer_context", "placement_hint"):
        value = context.get(field)
        if isinstance(value, dict):
            summary[field] = dict(value)
        elif value is not None and str(value).strip():
            summary[field] = str(value)
    return summary
