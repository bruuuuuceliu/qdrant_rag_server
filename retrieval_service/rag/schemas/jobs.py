"""Compatibility shim for project job schemas."""

from project_service.schemas.jobs import ProjectIngestJob

BaseIngestJob = ProjectIngestJob

__all__ = ["BaseIngestJob", "ProjectIngestJob"]
