"""Compatibility shim for project config schemas."""

from project_service.schemas.config import ProjectConfig

BaseProjectConfig = ProjectConfig

__all__ = ["BaseProjectConfig", "ProjectConfig"]
