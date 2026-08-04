"""Compatibility shim for project-service config repository."""

from project_service.config.repository import (
    DEFAULT_CONFIG_DB_PATH,
    PostgresProjectConfigRepository,
    ProjectConfigNotFoundError,
    ProjectConfigRecord,
    SQLiteProjectConfigRepository,
)

__all__ = [
    "DEFAULT_CONFIG_DB_PATH",
    "PostgresProjectConfigRepository",
    "ProjectConfigNotFoundError",
    "ProjectConfigRecord",
    "SQLiteProjectConfigRepository",
]
