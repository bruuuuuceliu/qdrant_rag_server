"""Compatibility shim for project schemas.

Canonical project schemas live in ``project_service.schemas``.
"""

from project_service.schemas import (
    BaseCacheScope,
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
    BaseIngestJob,
    BaseProjectConfig,
    BaseQueryScope,
    BaseRetrievalFilter,
    GenerateResult,
    GenerationUnavailableError,
    IngestResult,
    ProjectCacheScope,
    ProjectChunk,
    ProjectChunkPayload,
    ProjectConfig,
    ProjectDocument,
    ProjectIngestJob,
    ProjectQueryScope,
    ProjectRetrievalFilter,
    SearchResult,
)

__all__ = [
    "BaseCacheScope",
    "BaseChunk",
    "BaseChunkPayload",
    "BaseDocument",
    "BaseIngestJob",
    "BaseProjectConfig",
    "BaseQueryScope",
    "BaseRetrievalFilter",
    "GenerateResult",
    "GenerationUnavailableError",
    "IngestResult",
    "ProjectCacheScope",
    "ProjectChunk",
    "ProjectChunkPayload",
    "ProjectConfig",
    "ProjectDocument",
    "ProjectIngestJob",
    "ProjectQueryScope",
    "ProjectRetrievalFilter",
    "SearchResult",
]
