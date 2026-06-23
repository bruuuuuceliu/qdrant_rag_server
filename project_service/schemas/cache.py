"""Project-RAG cache scope schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from project_service.schemas.common import require_non_empty


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectCacheScope:
    project_id: str
    user_id: str
    query_hash: str
    scope_id: str = ""
    owner_id: str = ""
    cache_key: str = ""
    config_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", self.scope_id or self.project_id)
        object.__setattr__(self, "owner_id", self.owner_id or self.user_id)
        object.__setattr__(self, "cache_key", self.cache_key or self.query_hash)
        require_non_empty("scope_id", self.scope_id)
        require_non_empty("owner_id", self.owner_id)
        require_non_empty("cache_key", self.cache_key)
        require_non_empty("config_version", self.config_version)
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        require_non_empty("query_hash", self.query_hash)
