"""Shared data-type contracts for service routing.

These are transport-neutral route labels. Service-specific schemas, parsing,
filters, and indexing behavior stay in the owning service packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataType(StrEnum):
    PROJECT_DOCUMENT = "project_document"
    AGENT_MEMORY = "agent_memory"
    WORKFLOW_LOG = "workflow_log"


@dataclass(frozen=True, slots=True)
class DataTypeSpec:
    data_type: DataType
    owner_service: str
    executable: bool
    reserved_reason: str = ""


DATA_TYPE_REGISTRY: dict[DataType, DataTypeSpec] = {
    DataType.PROJECT_DOCUMENT: DataTypeSpec(
        data_type=DataType.PROJECT_DOCUMENT,
        owner_service="project_service",
        executable=True,
    ),
    DataType.AGENT_MEMORY: DataTypeSpec(
        data_type=DataType.AGENT_MEMORY,
        owner_service="memory_service",
        executable=False,
        reserved_reason="agent memory service is reserved for a future iteration",
    ),
    DataType.WORKFLOW_LOG: DataTypeSpec(
        data_type=DataType.WORKFLOW_LOG,
        owner_service="workflow_log_service",
        executable=False,
        reserved_reason="workflow log service is reserved for a future iteration",
    ),
}


def normalize_data_type(value: str | DataType | None) -> DataType:
    if value is None or not str(value).strip():
        return DataType.PROJECT_DOCUMENT
    try:
        return DataType(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"unsupported data_type: {value!r}") from exc


def data_type_spec(value: str | DataType | None) -> DataTypeSpec:
    return DATA_TYPE_REGISTRY[normalize_data_type(value)]
