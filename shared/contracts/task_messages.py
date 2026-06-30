"""Typed payload contracts for broker-driven task messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.contracts.messages import MessageEnvelope, MessageType, MessageValidationError
from shared.contracts.task_status import TaskStatus


@dataclass(frozen=True, slots=True)
class TaskRequestPayload:
    operation: str
    request: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    source_message_id: str = ""

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "TaskRequestPayload":
        _expect_type_in(envelope, MessageType.TASK_REQUEST, MessageType.REQUEST_ACCEPTED)
        return cls.from_payload(envelope.payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TaskRequestPayload":
        return cls(
            operation=_operation(payload),
            request=_mapping(payload.get("request", {}), "request"),
            context=_mapping(payload.get("context", {}), "context"),
            source_message_id=str(payload.get("source_message_id", "")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "request": dict(self.request),
            "context": dict(self.context),
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True, slots=True)
class ProjectPlanRequestPayload:
    operation: str
    request: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    source_message_id: str = ""

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "ProjectPlanRequestPayload":
        _expect_type_in(envelope, MessageType.PROJECT_PLAN_REQUEST, MessageType.DOMAIN_COMMAND)
        return cls.from_payload(envelope.payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ProjectPlanRequestPayload":
        return cls(
            operation=_operation(payload),
            request=_mapping(payload.get("request", {}), "request"),
            context=_mapping(payload.get("context", {}), "context"),
            source_message_id=str(payload.get("source_message_id", "")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "request": dict(self.request),
            "context": dict(self.context),
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True, slots=True)
class ProjectPlanResultPayload:
    operation: str
    plan: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    retryable: bool = False
    error: str = ""
    source_message_id: str = ""

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "ProjectPlanResultPayload":
        _expect_type_in(envelope, MessageType.PROJECT_PLAN_RESULT, MessageType.DOMAIN_RESULT)
        return cls.from_payload(envelope.payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ProjectPlanResultPayload":
        return cls(
            operation=_operation(payload),
            plan=_mapping(payload.get("plan", {}), "plan"),
            result=_mapping(payload.get("result", {}), "result"),
            attempt=_attempt(payload.get("attempt", 1)),
            retryable=bool(payload.get("retryable", False)),
            error=str(payload.get("error", "")),
            source_message_id=str(payload.get("source_message_id", "")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "plan": dict(self.plan),
            "result": dict(self.result),
            "attempt": self.attempt,
            "retryable": self.retryable,
            "error": self.error,
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True, slots=True)
class HelperCommandPayload:
    operation: str
    helper: str
    plan: dict[str, Any] = field(default_factory=dict)
    source_message_id: str = ""

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "HelperCommandPayload":
        _expect_type(envelope, MessageType.HELPER_COMMAND)
        return cls.from_payload(envelope.payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "HelperCommandPayload":
        helper = str(payload.get("helper", "")).strip()
        if not helper:
            raise MessageValidationError("helper command payload requires helper")
        return cls(
            operation=_operation(payload),
            helper=helper,
            plan=_mapping(payload.get("plan", {}), "plan"),
            source_message_id=str(payload.get("source_message_id", "")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "helper": self.helper,
            "plan": dict(self.plan),
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True, slots=True)
class HelperResultPayload:
    operation: str
    helper: str
    result: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    retryable: bool = False
    error: str = ""
    source_message_id: str = ""

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "HelperResultPayload":
        _expect_type(envelope, MessageType.HELPER_RESULT)
        return cls.from_payload(envelope.payload, fallback_helper=envelope.producer)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_helper: str = "",
    ) -> "HelperResultPayload":
        helper = str(payload.get("helper") or fallback_helper).strip()
        if not helper:
            raise MessageValidationError("helper result payload requires helper")
        return cls(
            operation=_operation(payload),
            helper=helper,
            result=_mapping(payload.get("result", {}), "result"),
            attempt=_attempt(payload.get("attempt", 1)),
            retryable=bool(payload.get("retryable", False)),
            error=str(payload.get("error", "")),
            source_message_id=str(payload.get("source_message_id", "")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "helper": self.helper,
            "result": dict(self.result),
            "attempt": self.attempt,
            "retryable": self.retryable,
            "error": self.error,
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True, slots=True)
class TaskEventPayload:
    operation: str
    status: str = TaskStatus.RUNNING.value
    event: str = "task.event"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    source_message_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "TaskEventPayload":
        _expect_type_in(
            envelope,
            MessageType.TASK_EVENT,
            MessageType.TASK_STARTED,
            MessageType.TASK_STEP,
        )
        return cls.from_payload(envelope.payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TaskEventPayload":
        return cls(
            operation=_operation(payload),
            status=_status(payload.get("status", TaskStatus.RUNNING.value)),
            event=str(payload.get("event", "task.event")),
            result=_mapping(payload.get("result", {}), "result"),
            error=str(payload.get("error", "")),
            source_message_id=str(payload.get("source_message_id", "")),
            context=_mapping(payload.get("context", {}), "context"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "event": self.event,
            "result": dict(self.result),
            "error": self.error,
            "source_message_id": self.source_message_id,
            "context": dict(self.context),
        }


@dataclass(frozen=True, slots=True)
class TaskStartedPayload:
    operation: str
    status: str = TaskStatus.RUNNING.value
    source_message_id: str = ""

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "TaskStartedPayload":
        _expect_type(envelope, MessageType.TASK_STARTED)
        return cls.from_payload(envelope.payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TaskStartedPayload":
        return cls(
            operation=_operation(payload),
            status=_status(payload.get("status", TaskStatus.RUNNING.value)),
            source_message_id=str(payload.get("source_message_id", "")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True, slots=True)
class TaskExecutionResultPayload:
    operation: str
    status: str
    result: dict[str, Any] = field(default_factory=dict)
    source_message_id: str = ""

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "TaskExecutionResultPayload":
        _expect_type(envelope, MessageType.TASK_RESULT)
        return cls.from_payload(envelope.payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TaskExecutionResultPayload":
        return cls(
            operation=_operation(payload),
            status=_status(payload.get("status", "")),
            result=_mapping(payload.get("result", {}), "result"),
            source_message_id=str(payload.get("source_message_id", "")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "result": dict(self.result),
            "source_message_id": self.source_message_id,
        }


@dataclass(frozen=True, slots=True)
class DeadLetterPayload:
    operation: str
    status: str = TaskStatus.FAILED.value
    source_topic: str = ""
    source_message_id: str = ""
    failed_message_id: str = ""
    attempt: int = 1
    retryable: bool = False
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DeadLetterPayload":
        return cls(
            operation=_operation(payload),
            status=_status(payload.get("status", TaskStatus.FAILED.value)),
            source_topic=str(payload.get("source_topic", "")),
            source_message_id=str(payload.get("source_message_id", "")),
            failed_message_id=str(payload.get("failed_message_id", "")),
            attempt=_attempt(payload.get("attempt", 1)),
            retryable=bool(payload.get("retryable", False)),
            error=str(payload.get("error", "")),
            result=_mapping(payload.get("result", {}), "result"),
            context=_mapping(payload.get("context", {}), "context"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "source_topic": self.source_topic,
            "source_message_id": self.source_message_id,
            "failed_message_id": self.failed_message_id,
            "attempt": self.attempt,
            "retryable": self.retryable,
            "error": self.error,
            "result": dict(self.result),
            "context": dict(self.context),
        }


def _expect_type(envelope: MessageEnvelope, expected: MessageType) -> None:
    if envelope.message_type != str(expected):
        raise MessageValidationError(
            f"expected {expected} message, got {envelope.message_type}"
        )


def _expect_type_in(envelope: MessageEnvelope, *expected: MessageType) -> None:
    expected_values = {str(item) for item in expected}
    if envelope.message_type not in expected_values:
        raise MessageValidationError(
            f"expected one of {', '.join(sorted(expected_values))} messages, got {envelope.message_type}"
        )


def _operation(payload: dict[str, Any]) -> str:
    operation = str(payload.get("operation", "")).strip()
    if not operation:
        raise MessageValidationError("task payload requires operation")
    return operation


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MessageValidationError(f"{field_name} must be a mapping")
    return dict(value)


def _status(value: Any) -> str:
    status = str(value).strip()
    if status not in {item.value for item in TaskStatus}:
        raise MessageValidationError(f"unsupported task status: {status}")
    return status


def _attempt(value: Any) -> int:
    try:
        attempt = int(value)
    except (TypeError, ValueError) as exc:
        raise MessageValidationError("attempt must be a positive integer") from exc
    if attempt < 1:
        raise MessageValidationError("attempt must be a positive integer")
    return attempt


TaskIntakePayload = TaskRequestPayload
DomainCommandPayload = ProjectPlanRequestPayload
DomainResultPayload = ProjectPlanResultPayload
TaskResultPayload = TaskExecutionResultPayload
