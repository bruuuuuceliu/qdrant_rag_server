"""Compatibility shim for ingest schemas."""

from project_service.schemas import ProjectIngestJob as BaseIngestJob
from retrieval_service.core.schemas.common import IngestJobStatus

__all__ = ["BaseIngestJob", "IngestJobStatus"]
