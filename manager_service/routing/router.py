"""Manager routing rules for service-boundary decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Operation(StrEnum):
    INGEST = "ingest"
    SEARCH = "search"
    DELETE = "delete"
    STATUS = "status"


class DataType(StrEnum):
    PROJECT_DOCUMENT = "project_document"
    AGENT_MEMORY = "agent_memory"
    WORKFLOW_LOG = "workflow_log"


class ServiceTarget(StrEnum):
    PROJECT = "project_service"
    RETRIEVAL = "retrieval_service"
    INGESTION = "ingestion_service"
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
        try:
            return DataType(self.data_type)
        except ValueError as exc:
            raise ValueError(f"unsupported data_type: {self.data_type!r}") from exc


@dataclass(frozen=True, slots=True)
class RouteDecision:
    operation: Operation
    data_type: DataType
    target_service: ServiceTarget
    executable: bool
    async_required: bool = False
    queue_topic: str = ""
    reason: str = ""

    @property
    def reserved(self) -> bool:
        return not self.executable


class ManagerRouter:
    """Routes public requests to the service that owns the requested work."""

    def __init__(
        self,
        *,
        ingest_topic: str = "ingestion.requests",
        workflow_topic: str = "workflow.events",
    ) -> None:
        self._ingest_topic = ingest_topic
        self._workflow_topic = workflow_topic

    def route(self, request: RouteRequest) -> RouteDecision:
        operation = request.normalized_operation()
        data_type = request.normalized_data_type()
        if data_type == DataType.PROJECT_DOCUMENT:
            return self._route_project_document(operation)
        if data_type == DataType.AGENT_MEMORY:
            return RouteDecision(
                operation=operation,
                data_type=data_type,
                target_service=ServiceTarget.MEMORY,
                executable=False,
                async_required=operation == Operation.INGEST,
                reason="agent memory service is reserved for a future iteration",
            )
        if data_type == DataType.WORKFLOW_LOG:
            return RouteDecision(
                operation=operation,
                data_type=data_type,
                target_service=ServiceTarget.WORKFLOW_LOG,
                executable=False,
                async_required=True,
                queue_topic=self._workflow_topic,
                reason="workflow log service is reserved for a future iteration",
            )
        raise ValueError(f"unsupported data_type: {data_type!r}")

    def _route_project_document(self, operation: Operation) -> RouteDecision:
        if operation == Operation.INGEST:
            return RouteDecision(
                operation=operation,
                data_type=DataType.PROJECT_DOCUMENT,
                target_service=ServiceTarget.INGESTION,
                executable=True,
                async_required=True,
                queue_topic=self._ingest_topic,
            )
        if operation in {Operation.SEARCH, Operation.DELETE}:
            return RouteDecision(
                operation=operation,
                data_type=DataType.PROJECT_DOCUMENT,
                target_service=ServiceTarget.RETRIEVAL,
                executable=True,
            )
        if operation == Operation.STATUS:
            return RouteDecision(
                operation=operation,
                data_type=DataType.PROJECT_DOCUMENT,
                target_service=ServiceTarget.INGESTION,
                executable=True,
            )
        raise ValueError(f"unsupported project_document operation: {operation!r}")
