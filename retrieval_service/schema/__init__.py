"""Compatibility shim for project-RAG schemas.

Prefer service-specific imports from ``project_service.schemas`` or
neutral shared imports from ``retrieval_service.core.schemas``.
"""

from retrieval_service.core.schemas import DEFAULT_KB_ID, IngestJobStatus, SHARED_USER_ID, Visibility
from project_service.schemas import (
    ProjectCacheScope as BaseCacheScope,
    ProjectChunk as BaseChunk,
    ProjectChunkPayload as BaseChunkPayload,
    ProjectConfig as BaseProjectConfig,
    ProjectDocument as BaseDocument,
    ProjectIngestJob as BaseIngestJob,
    ProjectQueryScope as BaseQueryScope,
    ProjectRetrievalFilter as BaseRetrievalFilter,
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
    "DEFAULT_KB_ID",
    "IngestJobStatus",
    "SHARED_USER_ID",
    "Visibility",
]
