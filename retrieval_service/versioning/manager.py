"""Compatibility shim for project-service version management."""

from project_service.versioning.manager import (
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
