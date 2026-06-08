"""Query scope and retrieval filter models."""

from __future__ import annotations

from dataclasses import dataclass

from retrieval_service.core.schemas.common import (
    SHARED_USER_ID,
    normalize_kb_ids,
    require_non_empty,
)


@dataclass(frozen=True, slots=True)
class BaseQueryScope:
    project_id: str
    user_id: str
    kb_ids: tuple[str, ...] = ()
    include_shared: bool = True

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        object.__setattr__(self, "kb_ids", normalize_kb_ids(self.kb_ids))


@dataclass(frozen=True, slots=True)
class BaseRetrievalFilter:
    project_id: str
    user_id: str
    kb_ids: tuple[str, ...] = ()
    doc_ids: tuple[str, ...] = ()
    shared_user_id: str | None = SHARED_USER_ID

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("user_id", self.user_id)
        object.__setattr__(self, "kb_ids", normalize_kb_ids(self.kb_ids))
        object.__setattr__(self, "doc_ids", tuple(self.doc_ids))

    @classmethod
    def from_scope(
        cls,
        scope: BaseQueryScope,
        *,
        doc_ids: tuple[str, ...] = (),
        shared_user_id: str = SHARED_USER_ID,
    ) -> "BaseRetrievalFilter":
        return cls(
            project_id=scope.project_id,
            user_id=scope.user_id,
            kb_ids=scope.kb_ids,
            doc_ids=doc_ids,
            shared_user_id=shared_user_id if scope.include_shared else None,
        )

    @property
    def allowed_user_ids(self) -> tuple[str, ...]:
        if self.shared_user_id is None:
            return (self.user_id,)
        return (self.user_id, self.shared_user_id)
