"""Gateway validation, coercion, and normalization helpers."""

from __future__ import annotations

from typing import Any

from project_service.gateway.errors import InvalidRequestError
from project_service.schemas import DEFAULT_KB_ID

FORBIDDEN_FILTER_KEYS = frozenset(
    {"filter", "filters", "qdrant_filter", "raw_filter", "raw_qdrant_filter"}
)


def _reject_raw_filters(data: dict[str, Any]) -> None:
    forbidden = FORBIDDEN_FILTER_KEYS.intersection(data)
    if forbidden:
        keys = ", ".join(sorted(forbidden))
        raise InvalidRequestError(f"client-supplied retrieval filters are forbidden: {keys}")


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise InvalidRequestError(f"{key} is required")
    _validate_non_empty(key, value)
    return value


def _normalize_optional_str(value: Any, default: str, *, field_name: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise InvalidRequestError(f"{field_name} must be a string")
    return value.strip() or default


def _validate_non_empty(field_name: str, value: str) -> None:
    if not value or not value.strip():
        raise InvalidRequestError(f"{field_name} is required")


def _validate_request_type(obj: Any, expected_type: str) -> None:
    if not isinstance(obj, (dict,)) and type(obj).__name__ not in expected_type.split("|"):
        raise InvalidRequestError(f"request must be {expected_type}")
