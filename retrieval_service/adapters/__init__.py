"""Compatibility shim for project adapters.

Canonical project adapters live in ``project_service.adapters``.
"""

from project_service.adapters import (
    AdapterNotFoundError,
    DuplicateAdapterError,
    ProjectAdapter,
    ProjectAdapterRegistry,
    ProjectAdapterResolver,
    ProjectTypeRepository,
    WEBSITE_PROJECT_TYPE,
    WebsiteChunkPayload,
    WebsiteDocument,
    WebsiteProjectAdapter,
    WebsiteProjectConfig,
)

__all__ = [
    "AdapterNotFoundError",
    "DuplicateAdapterError",
    "ProjectAdapter",
    "ProjectAdapterRegistry",
    "ProjectAdapterResolver",
    "ProjectTypeRepository",
    "WEBSITE_PROJECT_TYPE",
    "WebsiteChunkPayload",
    "WebsiteDocument",
    "WebsiteProjectAdapter",
    "WebsiteProjectConfig",
]
