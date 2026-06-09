"""Compatibility shim for shared schemas.

Prefer importing from ``retrieval_service.core.schemas``.
"""

from retrieval_service.core.schemas import (
    BaseCacheScope,
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
    BaseIngestJob,
    BaseProjectConfig,
    BaseServiceConfig,
    BaseQueryScope,
    BaseRetrievalFilter,
    DEFAULT_NAMESPACE,
    DEFAULT_KB_ID,
    SHARED_OWNER_ID,
    IngestJobStatus,
    JobStatus,
    SHARED_USER_ID,
    Visibility,
)

__all__ = [
    "BaseCacheScope",
    "BaseChunk",
    "BaseChunkPayload",
    "BaseDocument",
    "BaseIngestJob",
    "BaseProjectConfig",
    "BaseServiceConfig",
    "BaseQueryScope",
    "BaseRetrievalFilter",
    "DEFAULT_NAMESPACE",
    "DEFAULT_KB_ID",
    "SHARED_OWNER_ID",
    "IngestJobStatus",
    "JobStatus",
    "SHARED_USER_ID",
    "Visibility",
]
