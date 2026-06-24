"""Project-domain broker message handler."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from shared.contracts import (
    DomainCommandPayload,
    DomainResultPayload,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
)


class ProjectDomainHandler:
    """Handles task-manager project commands and returns project plans/info."""

    def __init__(self, *, planning: Any, producer: MessageProducer | None = None) -> None:
        self._planning = planning
        self._producer = producer

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        payload = DomainCommandPayload.from_envelope(envelope)
        operation = payload.operation
        request = payload.request
        if operation == "ingest":
            plan = await self._planning.plan_ingest(request)
        elif operation == "search":
            plan = await self._planning.plan_search(request)
        elif operation == "delete":
            plan = await self._planning.plan_delete(request)
        else:
            raise ValueError(f"unsupported project operation: {operation}")

        result = MessageEnvelope.create(
            producer="project_service",
            message_type=MessageType.DOMAIN_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=DomainResultPayload(
                operation=operation,
                plan=_plan_payload(plan),
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        if self._producer is not None:
            await self._producer.publish(TOPICS.domain_project_results, result, key=envelope.task_id)
        return result


def _plan_payload(plan: Any) -> dict[str, Any]:
    value = asdict(plan) if is_dataclass(plan) else dict(plan) if isinstance(plan, dict) else {}
    value.pop("raw_plan", None)
    value.pop("request", None)
    return _json_safe(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
