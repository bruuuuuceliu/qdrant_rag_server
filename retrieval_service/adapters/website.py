"""Compatibility shim for the project website adapter."""

from project_service.adapters.website import (
    WEBSITE_PROJECT_TYPE,
    WebsiteChunkPayload,
    WebsiteDocument,
    WebsiteProjectAdapter,
    WebsiteProjectConfig,
)

__all__ = [
    "WEBSITE_PROJECT_TYPE",
    "WebsiteChunkPayload",
    "WebsiteDocument",
    "WebsiteProjectAdapter",
    "WebsiteProjectConfig",
]
