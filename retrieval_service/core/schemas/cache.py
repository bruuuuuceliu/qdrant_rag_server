"""Universal cache scope model for retrieval-service cache keys."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import require_non_empty


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseCacheScope:
    scope_id: str = ""
    owner_id: str = ""
    cache_key: str = ""
    config_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("scope_id", self.scope_id)
        require_non_empty("owner_id", self.owner_id)
        require_non_empty("cache_key", self.cache_key)
        require_non_empty("config_version", self.config_version)
