"""Project-RAG query scope and retrieval filter schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import (
    SHARED_USER_ID,
    normalize_kb_ids,
    require_non_empty,
)
from retrieval_service.core.schemas.scope import BaseQueryScope, BaseRetrievalFilter


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectQueryScope(BaseQueryScope):
    project_id: str
    user_id: str
    kb_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_kb_ids = normalize_kb_ids(self.kb_ids)
        object.__setattr__(self, "kb_ids", normalized_kb_ids)
        object.__setattr__(self, "scope_id", self.scope_id or self.project_id)
        object.__setattr__(self, "owner_id", self.owner_id or self.user_id)
        object.__setattr__(self, "namespaces", self.namespaces or normalized_kb_ids)
        BaseQueryScope.__post_init__(self)
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectRetrievalFilter(BaseRetrievalFilter):
    project_id: str
    user_id: str
    kb_ids: tuple[str, ...] = ()
    doc_ids: tuple[str, ...] = ()
    shared_user_id: str | None = SHARED_USER_ID
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_kb_ids = normalize_kb_ids(self.kb_ids)
        normalized_doc_ids = tuple(self.doc_ids)
        object.__setattr__(self, "kb_ids", normalized_kb_ids)
        object.__setattr__(self, "doc_ids", normalized_doc_ids)
        object.__setattr__(self, "scope_id", self.scope_id or self.project_id)
        object.__setattr__(self, "owner_id", self.owner_id or self.user_id)
        object.__setattr__(self, "namespaces", self.namespaces or normalized_kb_ids)
        object.__setattr__(self, "resource_ids", self.resource_ids or normalized_doc_ids)
        object.__setattr__(self, "shared_owner_id", self.shared_user_id)
        BaseRetrievalFilter.__post_init__(self)
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)

    @classmethod
    def from_scope(
        cls,
        scope: ProjectQueryScope,
        *,
        doc_ids: tuple[str, ...] = (),
        shared_user_id: str = SHARED_USER_ID,
    ) -> "ProjectRetrievalFilter":
        return cls(
            project_id=scope.project_id,
            user_id=scope.user_id,
            scope_id=scope.scope_id,
            owner_id=scope.owner_id,
            kb_ids=scope.kb_ids,
            doc_ids=doc_ids,
            shared_user_id=shared_user_id if scope.include_shared else None,
            metadata=dict(scope.metadata),
        )

    @property
    def allowed_user_ids(self) -> tuple[str, ...]:
        if self.shared_user_id is None:
            return (self.user_id,)
        return (self.user_id, self.shared_user_id)
