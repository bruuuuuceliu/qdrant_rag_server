"""Shared domain schemas used across retrieval service packages."""

from retrieval_service.core.schemas.cache import BaseCacheScope
from retrieval_service.core.schemas.common import (
    DEFAULT_NAMESPACE,
    DEFAULT_KB_ID,
    SHARED_OWNER_ID,
    SHARED_USER_ID,
    JobStatus,
    IngestJobStatus,
    Visibility,
)
from retrieval_service.core.schemas.document import BaseChunk, BaseChunkPayload, BaseDocument
from retrieval_service.core.schemas.ingest import BaseIngestJob
from retrieval_service.core.schemas.project import BaseProjectConfig, BaseServiceConfig
from retrieval_service.core.schemas.scope import BaseQueryScope, BaseRetrievalFilter

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
