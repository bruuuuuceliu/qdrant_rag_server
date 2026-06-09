"""Shared constants, enums, and validation helpers used across domain models."""

from __future__ import annotations

from enum import StrEnum

DEFAULT_NAMESPACE = "default"
SHARED_OWNER_ID = "__shared__"

# Compatibility aliases for the project-RAG service. New shared code should use
# DEFAULT_NAMESPACE and SHARED_OWNER_ID instead.
DEFAULT_KB_ID = DEFAULT_NAMESPACE
SHARED_USER_ID = SHARED_OWNER_ID


class JobStatus(StrEnum):
    """Lifecycle states for asynchronous retrieval-service jobs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


IngestJobStatus = JobStatus


class Visibility(StrEnum):
    """Minimal record visibility marker."""

    PRIVATE = "private"
    SHARED = "shared"


def require_non_empty(field_name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")


def normalize_kb_id(value: str | None) -> str:
    if value is None or not str(value).strip():
        return DEFAULT_NAMESPACE
    return str(value).strip()


def normalize_kb_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def normalize_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def validate_visibility(value: str) -> None:
    allowed = {item.value for item in Visibility}
    if str(value) not in allowed:
        raise ValueError(f"visibility must be one of {sorted(allowed)}")
