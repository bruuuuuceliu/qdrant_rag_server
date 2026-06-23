"""Project-owned schema helpers."""

from __future__ import annotations

from enum import StrEnum


DEFAULT_KB_ID = "default"
SHARED_USER_ID = "__shared__"


class Visibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"


def require_non_empty(field_name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")


def normalize_kb_id(value: str | None) -> str:
    if value is None or not str(value).strip():
        return DEFAULT_KB_ID
    return str(value).strip()


def normalize_kb_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def normalize_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def validate_visibility(value: str) -> None:
    allowed = {item.value for item in Visibility}
    if str(value) not in allowed:
        raise ValueError(f"visibility must be one of {sorted(allowed)}")
