"""Compatibility shim for project adapter contracts.

Canonical project adapter implementations live in ``project_service.adapters``.
"""

from project_service.adapters.base import (
    AdapterNotFoundError,
    DuplicateAdapterError,
    ProjectAdapter,
    ProjectAdapterRegistry,
    ProjectAdapterResolver,
    ProjectTypeRepository,
)

__all__ = [
    "AdapterNotFoundError",
    "DuplicateAdapterError",
    "ProjectAdapter",
    "ProjectAdapterRegistry",
    "ProjectAdapterResolver",
    "ProjectTypeRepository",
]
