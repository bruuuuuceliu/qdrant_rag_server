"""Shared domain schemas used across retrieval service packages."""

from retrieval_service.core.schemas.cache import BaseCacheScope
from retrieval_service.core.schemas.common import (
    DEFAULT_KB_ID,
    SHARED_USER_ID,
    IngestJobStatus,
    Visibility,
)
from retrieval_service.core.schemas.document import BaseChunk, BaseChunkPayload, BaseDocument
from retrieval_service.core.schemas.ingest import BaseIngestJob
from retrieval_service.core.schemas.project import BaseProjectConfig
from retrieval_service.core.schemas.scope import BaseQueryScope, BaseRetrievalFilter

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
