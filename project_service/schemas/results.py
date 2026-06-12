"""RAG engine result schemas and exceptions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas import JobStatus


@dataclass
class SearchResult:
    chunks: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    cache_hit: bool = False


@dataclass
class IngestResult:
    job_id: str
    status: JobStatus
    doc_id: str = ""
    project_id: str = ""
    user_id: str = ""
    kb_id: str = ""
    data_type: str = "project_document"
    content_hash: str = ""
    raw_storage_key: str = ""
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class GenerateResult:
    response: str
    cache_hit: bool


class GenerationUnavailableError(RuntimeError):
    """Raised when answer generation is disabled for this deployment."""
