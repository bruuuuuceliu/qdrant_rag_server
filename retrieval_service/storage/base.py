"""Remote object storage abstraction for raw documents.

The engine uses this to store raw document content (for rebuilds) and
to fetch raw documents during re-indexing.  Query-time retrieval never
touches remote storage — text comes from Qdrant payloads.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class ObjectStorageError(Exception):
    """Raised when a storage operation fails."""


class ObjectStorage(ABC):
    """Abstract interface for remote object storage."""

    @abstractmethod
    async def put(self, key: str, content: bytes, content_type: str = "") -> None:
        """Store an object at the given key."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve an object by key."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object by key."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if an object exists."""


def _aws_sign(secret_key: str, date_stamp: str, region: str, string_to_sign: str) -> str:
    import hmac
    import hashlib as hl

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hl.sha256).digest()

    k_date = _sign(f"AWS4{secret_key}".encode(), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, "s3")
    k_signing = _sign(k_service, "aws4_request")
    return hmac.new(k_signing, string_to_sign.encode(), hl.sha256).hexdigest()


def make_storage_key(project_id: str, user_id: str, doc_id: str) -> str:
    """Generate a deterministic storage key for a document."""
    return f"{project_id}/{user_id}/{doc_id}"
