"""Project-RAG cache scope schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.cache import BaseCacheScope
from retrieval_service.core.schemas.common import require_non_empty


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectCacheScope(BaseCacheScope):
    project_id: str
    user_id: str
    query_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", self.scope_id or self.project_id)
        object.__setattr__(self, "owner_id", self.owner_id or self.user_id)
        object.__setattr__(self, "cache_key", self.cache_key or self.query_hash)
        BaseCacheScope.__post_init__(self)
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        require_non_empty("query_hash", self.query_hash)
