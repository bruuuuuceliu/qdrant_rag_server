"""Memory job schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import JobStatus, require_non_empty
from retrieval_service.core.schemas.ingest import BaseIngestJob


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryIngestJob(BaseIngestJob):
    owner_id: str
    memory_id: str
    agent_id: str = ""
    run_id: str = ""
    status: JobStatus = JobStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_name", self.service_name or "memory")
        object.__setattr__(self, "source_id", self.source_id or self.memory_id)
        object.__setattr__(self, "scope_id", self.scope_id or self.owner_id)
        BaseIngestJob.__post_init__(self)
        require_non_empty("owner_id", self.owner_id)
        require_non_empty("memory_id", self.memory_id)
