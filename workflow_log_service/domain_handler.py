"""Workflow-log domain broker handler."""

from __future__ import annotations

from typing import Any

from shared.contracts import (
    DomainCommandPayload,
    DomainResultPayload,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
)
from workflow_log_service.models import WorkflowLogEntry


class WorkflowLogDomainHandler:
    """Handles workflow-log domain commands and passive audit events."""

    def __init__(self, *, repository: Any, producer: MessageProducer | None = None) -> None:
        self._repository = repository
        self._producer = producer

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        if envelope.message_type == MessageType.AUDIT_EVENT:
            return await self.handle_audit_event(envelope)

        payload = DomainCommandPayload.from_envelope(envelope)
        operation = payload.operation
        if operation == "append":
            result = await self._append(envelope, payload)
        elif operation == "list":
            result = await self._list(payload)
        else:
            raise ValueError(f"unsupported workflow-log operation: {operation}")
        response = MessageEnvelope.create(
            producer="workflow_log_service",
            message_type=MessageType.DOMAIN_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=DomainResultPayload(
                operation=operation,
                result=result,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        if self._producer is not None:
            await self._producer.publish(TOPICS.domain_workflow_log_results, response, key=envelope.task_id)
        return response

    async def handle_audit_event(self, envelope: MessageEnvelope) -> MessageEnvelope:
        """Append an observational audit event without publishing a result."""

        payload = envelope.payload
        entry = WorkflowLogEntry(
            event=str(payload.get("event", envelope.message_type)),
            job_id=str(payload.get("job_id", envelope.task_id)),
            status=str(payload.get("status", "")),
            project_id=str(payload.get("project_id", "")),
            user_id=str(payload.get("user_id", "")),
            kb_id=str(payload.get("kb_id", "")),
            doc_id=str(payload.get("doc_id", "")),
            data_type=str(payload.get("data_type", envelope.data_type)),
            content_hash=str(payload.get("content_hash", "")),
            raw_storage_key=str(payload.get("raw_storage_key", "")),
            error=str(payload.get("error", "")),
            topic=TOPICS.audit_events,
            key=envelope.task_id,
            headers=dict(envelope.headers) | {"correlation_id": envelope.correlation_id},
            payload=dict(payload),
        )
        await self._repository.append(entry)
        return envelope

    async def _append(
        self,
        envelope: MessageEnvelope,
        command: DomainCommandPayload,
    ) -> dict[str, Any]:
        payload = command.request
        entry = WorkflowLogEntry(
            event=str(payload.get("event", "")),
            job_id=str(payload.get("job_id", envelope.task_id)),
            status=str(payload.get("status", "")),
            project_id=str(payload.get("project_id", "")),
            user_id=str(payload.get("user_id", "")),
            kb_id=str(payload.get("kb_id", "")),
            doc_id=str(payload.get("doc_id", "")),
            data_type=str(payload.get("data_type", "")),
            content_hash=str(payload.get("content_hash", "")),
            raw_storage_key=str(payload.get("raw_storage_key", "")),
            error=str(payload.get("error", "")),
            topic=TOPICS.audit_events,
            key=envelope.task_id,
            headers={"correlation_id": envelope.correlation_id},
            payload=dict(payload),
        )
        await self._repository.append(entry)
        return {"ok": True, "job_id": entry.job_id, "event": entry.event}

    async def _list(self, command: DomainCommandPayload) -> dict[str, Any]:
        job_id = str(command.request.get("job_id", ""))
        entries = await self._repository.list_by_job(job_id) if job_id else await self._repository.list_all()
        return {"ok": True, "entries": [_entry_payload(entry) for entry in entries]}


def _entry_payload(entry: WorkflowLogEntry) -> dict[str, Any]:
    return {
        "event": entry.event,
        "job_id": entry.job_id,
        "status": entry.status,
        "project_id": entry.project_id,
        "user_id": entry.user_id,
        "doc_id": entry.doc_id,
        "error": entry.error,
    }
