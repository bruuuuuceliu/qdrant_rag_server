"""Compatibility shim for shared schemas.

Prefer importing from ``retrieval_service.core.schemas``.
"""

from retrieval_service.core.schemas import (
    DEFAULT_KB_ID,
    DEFAULT_NAMESPACE,
    SHARED_OWNER_ID,
    SHARED_USER_ID,
    BaseCacheScope,
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
    BaseIngestJob,
    BaseQueryScope,
    BaseRetrievalFilter,
    BaseServiceConfig,
    IngestJobStatus,
    JobStatus,
    Visibility,
)

__all__ = [
    "BaseCacheScope",
    "BaseChunk",
    "BaseChunkPayload",
    "BaseDocument",
    "BaseIngestJob",
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
