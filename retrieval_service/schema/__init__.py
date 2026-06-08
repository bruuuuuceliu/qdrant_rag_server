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
    BaseQueryScope,
    BaseRetrievalFilter,
    DEFAULT_KB_ID,
    IngestJobStatus,
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
    "BaseQueryScope",
    "BaseRetrievalFilter",
    "DEFAULT_KB_ID",
    "IngestJobStatus",
    "SHARED_USER_ID",
    "Visibility",
]
