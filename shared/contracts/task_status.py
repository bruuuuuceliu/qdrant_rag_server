"""Task status contracts shared by manager, task manager, and Redis node."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class TaskStatus(StrEnum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    RUNNING = "running"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class TaskStatusRecord:
    task_id: str
    status: str
    correlation_id: str = ""
    data_type: str = ""
    operation: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task status requires task_id")
        if self.status not in {item.value for item in TaskStatus}:
            raise ValueError(f"unsupported task status: {self.status}")
        if not isinstance(self.result, dict):
            raise ValueError("task status result must be a mapping")

    def to_mapping(self) -> dict[str, Any]:
        self.validate()
        return {
            "task_id": self.task_id,
            "status": self.status,
            "correlation_id": self.correlation_id,
            "data_type": self.data_type,
            "operation": self.operation,
            "result": dict(self.result),
            "error": self.error,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> TaskStatusRecord:
        if not isinstance(value, dict):
            raise ValueError("task status record must be a mapping")
        result = value.get("result", {})
        return cls(
            task_id=str(value.get("task_id", "")),
            status=str(value.get("status", "")),
            correlation_id=str(value.get("correlation_id", "")),
            data_type=str(value.get("data_type", "")),
            operation=str(value.get("operation", "")),
            result=dict(result if isinstance(result, dict) else {}),
            error=str(value.get("error", "")),
        )


class TaskStatusStore(Protocol):
    async def set_status(self, record: TaskStatusRecord, *, ttl_seconds: int | None = None) -> None:
        ...

    async def get_status(self, task_id: str) -> TaskStatusRecord | None:
        ...
