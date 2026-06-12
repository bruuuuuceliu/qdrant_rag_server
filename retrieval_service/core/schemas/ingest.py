"""Universal job model for asynchronous retrieval-service work."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import JobStatus, require_non_empty


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseIngestJob:
    job_id: str
    service_name: str = ""
    source_id: str = ""
    status: JobStatus = JobStatus.PENDING
    owner_id: str = ""
    scope_id: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        require_non_empty("job_id", self.job_id)
        require_non_empty("service_name", self.service_name)
        require_non_empty("source_id", self.source_id)
