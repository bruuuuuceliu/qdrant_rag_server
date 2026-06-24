"""Retrieval helper broker handler."""

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


class RetrievalHelperHandler:
    """Handles task-manager-issued retrieval helper commands."""

    def __init__(self, *, api: Any, producer: MessageProducer | None = None) -> None:
        self._api = api
        self._producer = producer

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        payload = HelperCommandPayload.from_envelope(envelope)
        operation = payload.operation
        if operation == "search":
            result = await self._run_search(envelope, payload)
        elif operation == "delete":
            result = await self._run_delete(envelope, payload)
        else:
            raise ValueError(f"unsupported retrieval helper operation: {operation}")
        response = MessageEnvelope.create(
            producer="retrieval_service",
            message_type=MessageType.HELPER_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=HelperResultPayload(
                operation=operation,
                helper=payload.helper,
                result=result,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        if self._producer is not None:
            await self._producer.publish(TOPICS.helper_retrieval_results, response, key=envelope.task_id)
        return response

    async def _run_search(
        self,
        envelope: MessageEnvelope,
        payload: HelperCommandPayload,
    ) -> dict[str, Any]:
        search = getattr(self._api, "search", None)
        if search is None:
            return {"ok": False, "error": "retrieval search API is not configured"}
        result = await search(payload.plan, fallback_request_id=envelope.task_id)
        return result if isinstance(result, dict) else {"ok": True, "value": str(result)}

    async def _run_delete(
        self,
        envelope: MessageEnvelope,
        payload: HelperCommandPayload,
    ) -> dict[str, Any]:
        delete_document = getattr(self._api, "delete_document", None)
        if delete_document is None:
            return {"ok": False, "error": "retrieval delete API is not configured"}
        result = await delete_document(payload.plan, fallback_request_id=envelope.task_id)
        return result if isinstance(result, dict) else {"ok": True, "value": str(result)}
