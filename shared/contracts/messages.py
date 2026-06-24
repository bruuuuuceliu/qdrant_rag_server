"""Stable broker message contracts.

These DTOs are intentionally small and transport-neutral. Services may import
them as external contracts, but must not import another service's internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4


CURRENT_SCHEMA_VERSION = "1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({CURRENT_SCHEMA_VERSION})


class MessageValidationError(ValueError):
    """Raised when a broker message does not satisfy the shared contract."""


class MessageType(StrEnum):
    REQUEST_ACCEPTED = "request.accepted"
    REQUEST_REJECTED = "request.rejected"
    DOMAIN_COMMAND = "domain.command"
    DOMAIN_RESULT = "domain.result"
    HELPER_COMMAND = "helper.command"
    HELPER_RESULT = "helper.result"
    TASK_STARTED = "task.started"
    TASK_STEP = "task.step"
    TASK_RESULT = "task.result"
    AUDIT_EVENT = "audit.event"
    METRIC_EVENT = "metric.event"
    HEALTH_EVENT = "health.event"


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    message_id: str
    correlation_id: str
    task_id: str
    producer: str
    message_type: str
    data_type: str
    schema_version: str
    created_at: str
    headers: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        producer: str,
        message_type: str | MessageType,
        data_type: str,
        payload: dict[str, Any] | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
        message_id: str | None = None,
        schema_version: str = "1",
        headers: dict[str, str] | None = None,
        created_at: str | None = None,
    ) -> MessageEnvelope:
        envelope = cls(
            message_id=message_id or uuid4().hex,
            correlation_id=correlation_id or uuid4().hex,
            task_id=task_id or uuid4().hex,
            producer=producer,
            message_type=str(message_type),
            data_type=data_type,
            schema_version=schema_version,
            created_at=created_at or datetime.now(UTC).isoformat(),
            headers=dict(headers or {}),
            payload=dict(payload or {}),
        )
        envelope.validate()
        return envelope

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> MessageEnvelope:
        envelope = cls(
            message_id=str(value.get("message_id", "")),
            correlation_id=str(value.get("correlation_id", "")),
            task_id=str(value.get("task_id", "")),
            producer=str(value.get("producer", "")),
            message_type=str(value.get("message_type", "")),
            data_type=str(value.get("data_type", "")),
            schema_version=str(value.get("schema_version", "")),
            created_at=str(value.get("created_at", "")),
            headers=_string_map(value.get("headers", {}), "headers"),
            payload=_payload_map(value.get("payload", {})),
        )
        envelope.validate()
        return envelope

    def to_mapping(self) -> dict[str, Any]:
        self.validate()
        return {
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "task_id": self.task_id,
            "producer": self.producer,
            "message_type": self.message_type,
            "data_type": self.data_type,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "headers": dict(self.headers),
            "payload": dict(self.payload),
        }

    def validate(self) -> None:
        required = {
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "task_id": self.task_id,
            "producer": self.producer,
            "message_type": self.message_type,
            "data_type": self.data_type,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise MessageValidationError(f"missing message fields: {', '.join(missing)}")
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise MessageValidationError(f"unsupported schema_version: {self.schema_version}")
        if self.message_type not in {item.value for item in MessageType}:
            raise MessageValidationError(f"unsupported message_type: {self.message_type}")
        if not isinstance(self.headers, dict):
            raise MessageValidationError("headers must be a mapping")
        if not isinstance(self.payload, dict):
            raise MessageValidationError("payload must be a mapping")


@runtime_checkable
class MessageProducer(Protocol):
    async def publish(self, topic: str, envelope: MessageEnvelope, *, key: str = "") -> None:
        """Publish one message envelope."""


@runtime_checkable
class MessageConsumer(Protocol):
    async def consume(self, topic: str) -> MessageEnvelope:
        """Consume one message envelope."""


def _string_map(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MessageValidationError(f"{field_name} must be a mapping")
    return {str(key): str(item) for key, item in value.items()}


def _payload_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MessageValidationError("payload must be a mapping")
    return dict(value)
