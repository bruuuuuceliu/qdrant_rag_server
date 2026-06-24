"""Storage helper broker handler."""

from __future__ import annotations

from shared.contracts import (
    HelperCommandPayload,
    HelperResultPayload,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    TOPICS,
)


class StorageHelperHandler:
    """Handles task-manager-issued storage helper commands."""

    def __init__(self, *, storage: object, producer: MessageProducer | None = None) -> None:
        self._storage = storage
        self._producer = producer

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        payload = HelperCommandPayload.from_envelope(envelope)
        result = await self._run(payload)
        response = MessageEnvelope.create(
            producer="storage_node",
            message_type=MessageType.HELPER_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=HelperResultPayload(
                operation=payload.operation,
                helper=TOPICS.helper_storage_commands,
                result=result,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        if self._producer is not None:
            await self._producer.publish(TOPICS.helper_storage_results, response, key=envelope.task_id)
        return response

    async def _run(self, payload: HelperCommandPayload) -> dict[str, object]:
        plan = payload.plan
        operation = str(plan.get("operation") or payload.operation)
        key = str(plan.get("key") or plan.get("storage_key") or plan.get("raw_storage_key") or "")
        if operation == "put":
            result = await self._storage.put(key=key, value=str(plan.get("value", "")))
        elif operation == "get":
            result = await self._storage.get(key=key)
        elif operation == "delete":
            result = await self._storage.delete(key=key)
        else:
            raise ValueError(f"unsupported storage operation: {operation}")
        return result.to_payload()
