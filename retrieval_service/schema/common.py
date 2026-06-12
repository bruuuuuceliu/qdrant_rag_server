"""Compatibility shim for shared schema helpers."""

from retrieval_service.core.schemas.common import (
    DEFAULT_NAMESPACE,
    DEFAULT_KB_ID,
    SHARED_OWNER_ID,
    SHARED_USER_ID,
    JobStatus,
    IngestJobStatus,
    Visibility,
    normalize_ids,
    normalize_kb_id,
    normalize_kb_ids,
    require_non_empty,
    validate_visibility,
)

__all__ = [
    "DEFAULT_NAMESPACE",
    "DEFAULT_KB_ID",
    "SHARED_OWNER_ID",
    "IngestJobStatus",
    "JobStatus",
    "SHARED_USER_ID",
    "Visibility",
    "normalize_ids",
    "normalize_kb_id",
    "normalize_kb_ids",
    "require_non_empty",
    "validate_visibility",
]
