"""Compatibility shim for ingest schemas."""

from retrieval_service.core.schemas.ingest import BaseIngestJob
from retrieval_service.core.schemas.common import IngestJobStatus

__all__ = ["BaseIngestJob", "IngestJobStatus"]
