"""Stable configuration package exports."""

from __future__ import annotations

from configs.config import AppSettings, load_settings
from configs.validation import (
    ConfigValidationIssue,
    ConfigValidationResult,
    validate_settings,
    validate_settings_or_raise,
)

_PROJECT_EXPORTS = {
    "PostgresProjectConfigRepository",
    "ProjectConfigNotFoundError",
    "ProjectConfigRecord",
}


def __getattr__(name: str):
    if name in _PROJECT_EXPORTS:
        from configs import project

        return getattr(project, name)
    raise AttributeError(f"module 'configs' has no attribute {name!r}")


__all__ = [
    "AppSettings",
    "ConfigValidationIssue",
    "ConfigValidationResult",
    "PostgresProjectConfigRepository",
    "ProjectConfigNotFoundError",
    "ProjectConfigRecord",
    "load_settings",
    "validate_settings",
    "validate_settings_or_raise",
]
