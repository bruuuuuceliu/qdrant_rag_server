"""Manager routing rules for service-boundary decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from shared.contracts import DataType, data_type_spec, normalize_data_type


class Operation(StrEnum):
    INGEST = "ingest"
    SEARCH = "search"
    DELETE = "delete"
    STATUS = "status"


class ServiceTarget(StrEnum):
    TASK_MANAGER = "task_manager_service"
    TASK_STATUS = "task_status_store"
    MEMORY = "memory_service"
    WORKFLOW_LOG = "workflow_log_service"


@dataclass(frozen=True, slots=True)
class RouteRequest:
    operation: str
    data_type: str = DataType.PROJECT_DOCUMENT
    project_id: str = ""
    user_id: str = ""
    kb_id: str = ""
    service_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_operation(self) -> Operation:
        try:
            return Operation(self.operation)
        except ValueError as exc:
            raise ValueError(f"unsupported manager operation: {self.operation!r}") from exc

    def normalized_data_type(self) -> DataType:
        return normalize_data_type(self.data_type)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    operation: Operation
    data_type: DataType
    target_service: ServiceTarget
    executable: bool
    reason: str = ""

    @property
    def reserved(self) -> bool:
        return not self.executable


class ManagerRouter:
    """Routes public requests to the service that owns the requested work."""

    def route(self, request: RouteRequest) -> RouteDecision:
        operation = request.normalized_operation()
        data_type = request.normalized_data_type()
        if data_type == DataType.PROJECT_DOCUMENT:
            return self._route_project_document(operation)
        if data_type == DataType.AGENT_MEMORY:
            spec = data_type_spec(data_type)
            return RouteDecision(
                operation=operation,
                data_type=data_type,
                target_service=ServiceTarget.MEMORY,
                executable=False,
                reason=spec.reserved_reason,
            )
        if data_type == DataType.WORKFLOW_LOG:
            spec = data_type_spec(data_type)
            return RouteDecision(
                operation=operation,
                data_type=data_type,
                target_service=ServiceTarget.WORKFLOW_LOG,
                executable=False,
                reason=spec.reserved_reason,
            )
        raise ValueError(f"unsupported data_type: {data_type!r}")

    def _route_project_document(self, operation: Operation) -> RouteDecision:
        if operation == Operation.INGEST:
            return RouteDecision(
                operation=operation,
                data_type=DataType.PROJECT_DOCUMENT,
                target_service=ServiceTarget.TASK_MANAGER,
                executable=True,
            )
        if operation in {Operation.SEARCH, Operation.DELETE}:
            return RouteDecision(
                operation=operation,
                data_type=DataType.PROJECT_DOCUMENT,
                target_service=ServiceTarget.TASK_MANAGER,
                executable=True,
            )
        if operation == Operation.STATUS:
            return RouteDecision(
                operation=operation,
                data_type=DataType.PROJECT_DOCUMENT,
                target_service=ServiceTarget.TASK_STATUS,
                executable=True,
            )
        raise ValueError(f"unsupported project_document operation: {operation!r}")
