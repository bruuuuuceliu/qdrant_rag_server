"""Memory query scope and retrieval filter schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import normalize_ids, require_non_empty
from retrieval_service.core.schemas.scope import BaseQueryScope, BaseRetrievalFilter


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryQueryScope(BaseQueryScope):
    owner_id: str
    agent_id: str = ""
    run_id: str = ""
    include_shared: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", self.scope_id or self.owner_id)
        BaseQueryScope.__post_init__(self)
        require_non_empty("owner_id", self.owner_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRetrievalFilter(BaseRetrievalFilter):
    owner_id: str
    agent_ids: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    memory_ids: tuple[str, ...] = ()
    memory_types: tuple[str, ...] = ()
    shared_owner_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        memory_ids = normalize_ids(self.memory_ids)
        object.__setattr__(self, "scope_id", self.scope_id or self.owner_id)
        object.__setattr__(self, "resource_ids", self.resource_ids or memory_ids)
        object.__setattr__(self, "agent_ids", normalize_ids(self.agent_ids))
        object.__setattr__(self, "run_ids", normalize_ids(self.run_ids))
        object.__setattr__(self, "memory_ids", memory_ids)
        object.__setattr__(self, "memory_types", normalize_ids(self.memory_types))
        BaseRetrievalFilter.__post_init__(self)
        require_non_empty("owner_id", self.owner_id)

    @classmethod
    def from_scope(
        cls,
        scope: MemoryQueryScope,
        *,
        memory_ids: tuple[str, ...] = (),
        memory_types: tuple[str, ...] = (),
    ) -> "MemoryRetrievalFilter":
        agent_ids = (scope.agent_id,) if scope.agent_id else ()
        run_ids = (scope.run_id,) if scope.run_id else ()
        return cls(
            owner_id=scope.owner_id,
            scope_id=scope.scope_id,
            agent_ids=agent_ids,
            run_ids=run_ids,
            memory_ids=memory_ids,
            memory_types=memory_types,
            metadata=dict(scope.metadata),
        )
