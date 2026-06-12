"""Compatibility shim for project cache schemas."""

from project_service.schemas.cache import ProjectCacheScope

BaseCacheScope = ProjectCacheScope

__all__ = ["BaseCacheScope", "ProjectCacheScope"]
