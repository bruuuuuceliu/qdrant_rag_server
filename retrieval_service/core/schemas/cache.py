"""Cache scope model for response cache key construction."""

from __future__ import annotations

from dataclasses import dataclass

from retrieval_service.core.schemas.common import require_non_empty


@dataclass(frozen=True, slots=True)
class BaseCacheScope:
    project_id: str
    user_id: str
    query_hash: str
    config_version: str

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        require_non_empty("query_hash", self.query_hash)
        require_non_empty("config_version", self.config_version)
