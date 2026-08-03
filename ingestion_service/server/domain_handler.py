"""Ingestion helper broker handler."""

from __future__ import annotations

from typing import Any

from shared.contracts import (
    HelperCommandPayload,
    HelperResultPayload,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
)


class IngestionHelperHandler:
    """Handles task-service-issued ingestion helper commands."""

    def __init__(self, *, app: Any, producer: MessageProducer | None = None) -> None:
        self._app = app
        self._producer = producer

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        payload = HelperCommandPayload.from_envelope(envelope)
        operation = payload.operation
        if operation != "ingest":
            raise ValueError(f"unsupported ingestion helper operation: {operation}")
        result = await self._run_ingest(payload, fallback_request_id=envelope.task_id)
        response = MessageEnvelope.create(
            producer="ingestion_service",
            message_type=MessageType.HELPER_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=HelperResultPayload(
                operation=operation,
                helper=payload.helper,
                result=result,
                attempt=payload.attempt,
                retryable=bool(result.get("retryable", False)),
                error=str(result.get("error", "")) if result.get("ok") is False else "",
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        if self._producer is not None:
            await self._producer.publish(TOPICS.helper_ingestion_results, response, key=envelope.task_id)
        return response

    async def _run_ingest(
        self,
        payload: HelperCommandPayload,
        *,
        fallback_request_id: str,
    ) -> dict[str, Any]:
        start_ingest = getattr(self._app, "start_ingest", None)
        if start_ingest is None:
            return {"ok": False, "error": "ingestion helper app is not configured"}
        plan = dict(payload.plan)
        plan.setdefault("request_id", fallback_request_id)
        result = await start_ingest(plan)
        return result if isinstance(result, dict) else {"ok": True, "value": str(result)}
