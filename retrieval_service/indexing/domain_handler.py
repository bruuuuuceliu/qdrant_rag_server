"""Retrieval-index helper broker handler."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import logging
from typing import Any

from retrieval_service.indexing.commands import RetrievalIndexCommand
from shared.contracts import (
    HelperCommandPayload,
    HelperResultPayload,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
)


logger = logging.getLogger(__name__)


class RetrievalIndexHelperHandler:
    """Handles task-service-issued retrieval-index helper commands."""

    def __init__(self, *, indexing_service: Any, producer: MessageProducer | None = None) -> None:
        self._indexing_service = indexing_service
        self._producer = producer

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        payload = HelperCommandPayload.from_envelope(envelope)
        if payload.operation != "ingest":
            raise ValueError(f"unsupported retrieval-index operation: {payload.operation}")
        result = await self._run_index(envelope, payload)
        response = MessageEnvelope.create(
            producer="retrieval_service",
            message_type=MessageType.HELPER_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=HelperResultPayload(
                operation=payload.operation,
                helper=TOPICS.helper_retrieval_index_commands,
                result=result,
                attempt=payload.attempt,
                retryable=bool(result.get("retryable", False)),
                error=str(result.get("error", "")) if result.get("ok") is False else "",
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        if self._producer is not None:
            await self._producer.publish(TOPICS.helper_retrieval_index_results, response, key=envelope.task_id)
        return response

    async def _run_index(
        self,
        envelope: MessageEnvelope,
        payload: HelperCommandPayload,
    ) -> dict[str, Any]:
        index_chunks = getattr(self._indexing_service, "index_chunks", None)
        if index_chunks is None:
            return {"ok": False, "error": "retrieval indexing service is not configured"}
        try:
            command = RetrievalIndexCommand.from_payload(
                payload.plan,
                fallback_request_id=envelope.task_id,
            )
            result = await index_chunks(command.to_index_request())
        except Exception as exc:
            logger.exception(
                "retrieval-index helper failed task_id=%s source_message_id=%s",
                envelope.task_id,
                envelope.message_id,
            )
            return {"ok": False, "error": str(exc), "retryable": False}
        return {"ok": True, **_result_to_payload(result)}


def _result_to_payload(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, dict):
        return dict(result)
    return dict(getattr(result, "__dict__", {}))
