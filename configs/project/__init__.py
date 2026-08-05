"""Compatibility shim for project-service config exports."""

from project_service.config import (
    PostgresProjectConfigRepository,
    ProjectConfigNotFoundError,
    ProjectConfigRecord,
)

__all__ = [
    "PostgresProjectConfigRepository",
    "ProjectConfigNotFoundError",
    "ProjectConfigRecord",
]
