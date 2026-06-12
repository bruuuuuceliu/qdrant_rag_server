"""Project-RAG job schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import JobStatus, require_non_empty
from retrieval_service.core.schemas.ingest import BaseIngestJob


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectIngestJob(BaseIngestJob):
    project_id: str
    user_id: str
    doc_id: str
    source_uri: str
    status: JobStatus = JobStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_name", self.service_name or "project_rag")
        object.__setattr__(self, "source_id", self.source_id or self.doc_id)
        object.__setattr__(self, "owner_id", self.owner_id or self.user_id)
        object.__setattr__(self, "scope_id", self.scope_id or self.project_id)
        BaseIngestJob.__post_init__(self)
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        require_non_empty("doc_id", self.doc_id)
        require_non_empty("source_uri", self.source_uri)
