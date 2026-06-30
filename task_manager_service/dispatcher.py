"""Task manager intake and status read-model core."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from shared.contracts import (
    MessageConsumer,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
    TaskEventPayload,
    TaskExecutionResultPayload,
    TaskRequestPayload,
    TaskStatus,
    TaskStatusRecord,
    TaskStatusStore,
)
from task_manager_service.config import TaskManagerSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    task_id: str
    data_type: str
    operation: str
    task_request_topic: str


@dataclass(frozen=True, slots=True)
class StatusUpdateResult:
    task_id: str
    operation: str
    status: str


class TaskManagerDispatcher:
    """Normalizes client task intake and maintains the Redis status read model."""

    def __init__(
        self,
        *,
        producer: MessageProducer,
        status_store: TaskStatusStore | None = None,
        settings: TaskManagerSettings | None = None,
    ) -> None:
        self._producer = producer
        self._status_store = status_store
        self._settings = settings or TaskManagerSettings()

    async def dispatch_intake(self, envelope: MessageEnvelope) -> DispatchResult:
        payload = TaskRequestPayload.from_envelope(envelope)
        operation = payload.operation
        logger.info(
            "task manager intake task_id=%s operation=%s data_type=%s task_request_topic=%s",
            envelope.task_id,
            operation,
            envelope.data_type,
            self._settings.task_request_topic,
        )
        await self._write_status(envelope, operation=operation, status=TaskStatus.QUEUED)
        await self._publish_task_request(envelope, payload=payload)
        return DispatchResult(
            task_id=envelope.task_id,
            data_type=envelope.data_type,
            operation=operation,
            task_request_topic=self._settings.task_request_topic,
        )

    async def run_once(self, consumer: MessageConsumer) -> DispatchResult:
        envelope = await consumer.consume(self._settings.task_intake_topic)
        return await self.dispatch_intake(envelope)

    async def update_from_task_event(self, envelope: MessageEnvelope) -> StatusUpdateResult:
        payload = TaskEventPayload.from_envelope(envelope)
        ttl_seconds = (
            self._settings.completed_ttl_seconds
            if payload.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value)
            else None
        )
        await self._write_status(
            envelope,
            operation=payload.operation,
            status=payload.status,
            result=payload.result,
            error=payload.error,
            ttl_seconds=ttl_seconds,
        )
        return StatusUpdateResult(
            task_id=envelope.task_id,
            operation=payload.operation,
            status=payload.status,
        )

    async def update_from_task_result(self, envelope: MessageEnvelope) -> StatusUpdateResult:
        payload = TaskExecutionResultPayload.from_envelope(envelope)
        await self._write_status(
            envelope,
            operation=payload.operation,
            status=payload.status,
            result=payload.result,
            ttl_seconds=self._settings.completed_ttl_seconds,
        )
        return StatusUpdateResult(
            task_id=envelope.task_id,
            operation=payload.operation,
            status=payload.status,
        )

    async def _publish_task_request(
        self,
        envelope: MessageEnvelope,
        *,
        payload: TaskRequestPayload,
    ) -> None:
        request = MessageEnvelope.create(
            producer=self._settings.service_name,
            message_type=MessageType.TASK_REQUEST,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=TaskRequestPayload(
                operation=payload.operation,
                request=payload.request,
                context=payload.context,
                source_message_id=payload.source_message_id or envelope.message_id,
            ).to_payload(),
        )
        await self._producer.publish(
            self._settings.task_request_topic,
            request,
            key=envelope.task_id,
        )
        logger.info(
            "task manager publish task_request task_id=%s operation=%s topic=%s",
            envelope.task_id,
            payload.operation,
            self._settings.task_request_topic,
        )

    async def _write_status(
        self,
        envelope: MessageEnvelope,
        *,
        operation: str,
        status: str | TaskStatus,
        result: dict[str, Any] | None = None,
        error: str = "",
        ttl_seconds: int | None = None,
    ) -> None:
        if self._status_store is None:
            return
        logger.info(
            "task manager status write task_id=%s operation=%s status=%s ttl_seconds=%s",
            envelope.task_id,
            operation,
            str(status),
            ttl_seconds if ttl_seconds is not None else "",
        )
        await self._status_store.set_status(
            TaskStatusRecord(
                task_id=envelope.task_id,
                status=str(status),
                correlation_id=envelope.correlation_id,
                data_type=envelope.data_type,
                operation=operation,
                result=dict(result or {}),
                error=error,
            ),
            ttl_seconds=ttl_seconds,
        )


FinalizeResult = StatusUpdateResult
HelperDispatchResult = StatusUpdateResult
