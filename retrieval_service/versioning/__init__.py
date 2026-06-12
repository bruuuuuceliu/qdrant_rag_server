"""Compatibility shim for project-service versioning."""

from project_service.versioning import (
    DEFAULT_GRACE_PERIOD_SECONDS,
    VersionInfo,
    VersionManager,
    VersionNotFoundError,
)

__all__ = [
    "DEFAULT_GRACE_PERIOD_SECONDS",
    "VersionInfo",
    "VersionManager",
    "VersionNotFoundError",
]
