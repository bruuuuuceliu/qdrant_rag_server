"""Universal query scope and retrieval filter primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import (
    SHARED_OWNER_ID,
    normalize_ids,
    require_non_empty,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseQueryScope:
    """A neutral ownership boundary for retrieval requests."""

    scope_id: str = ""
    owner_id: str = ""
    namespaces: tuple[str, ...] = ()
    include_shared: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("scope_id", self.scope_id)
        require_non_empty("owner_id", self.owner_id)
        object.__setattr__(self, "namespaces", normalize_ids(self.namespaces))


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseRetrievalFilter:
    """A neutral retrieval intent envelope.

    Backends should translate this into their native filter type instead of
    letting backend details leak into shared schemas.
    """

    scope_id: str = ""
    owner_id: str = ""
    namespaces: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    shared_owner_id: str | None = SHARED_OWNER_ID
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("scope_id", self.scope_id)
        require_non_empty("owner_id", self.owner_id)
        object.__setattr__(self, "namespaces", normalize_ids(self.namespaces))
        object.__setattr__(self, "resource_ids", normalize_ids(self.resource_ids))

    @classmethod
    def from_scope(
        cls,
        scope: BaseQueryScope,
        *,
        resource_ids: tuple[str, ...] = (),
        shared_owner_id: str = SHARED_OWNER_ID,
    ) -> "BaseRetrievalFilter":
        return cls(
            scope_id=scope.scope_id,
            owner_id=scope.owner_id,
            namespaces=scope.namespaces,
            resource_ids=resource_ids,
            shared_owner_id=shared_owner_id if scope.include_shared else None,
            metadata=dict(scope.metadata),
        )

    @property
    def allowed_owner_ids(self) -> tuple[str, ...]:
        if self.shared_owner_id is None:
            return (self.owner_id,)
        return (self.owner_id, self.shared_owner_id)
