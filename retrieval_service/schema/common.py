"""Compatibility shim for shared schema helpers."""

from retrieval_service.core.schemas.common import (
    DEFAULT_KB_ID,
    SHARED_USER_ID,
    IngestJobStatus,
    Visibility,
    normalize_kb_id,
    normalize_kb_ids,
    require_non_empty,
    validate_visibility,
)

__all__ = [
    "DEFAULT_KB_ID",
    "IngestJobStatus",
    "SHARED_USER_ID",
    "Visibility",
    "normalize_kb_id",
    "normalize_kb_ids",
    "require_non_empty",
    "validate_visibility",
]
