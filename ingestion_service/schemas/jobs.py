"""Ingestion job status schemas."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from shared.contracts import JobStatus


@dataclass(slots=True, kw_only=True)
class IngestionJob:
    job_id: str
    source_uri: str
    document_id: str
    status: JobStatus = JobStatus.PENDING
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
