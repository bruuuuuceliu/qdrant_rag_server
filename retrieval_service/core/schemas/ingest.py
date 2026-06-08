"""Ingest job model for tracking asynchronous document ingestion."""

from __future__ import annotations

from dataclasses import dataclass

from retrieval_service.core.schemas.common import IngestJobStatus, require_non_empty


@dataclass(frozen=True, slots=True)
class BaseIngestJob:
    project_id: str
    user_id: str
    doc_id: str
    source_uri: str
    status: IngestJobStatus = IngestJobStatus.PENDING
    error: str | None = None

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        require_non_empty("doc_id", self.doc_id)
        require_non_empty("source_uri", self.source_uri)
