"""Project configuration model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval_service.core.schemas.common import require_non_empty


@dataclass(frozen=True, slots=True)
class BaseProjectConfig:
    project_id: str
    project_type: str
    active_embedding_version: str
    embedding_model: str
    reranker_model: str
    chunker_config: dict[str, Any] = field(default_factory=dict)
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    cache_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("project_type", self.project_type)
        require_non_empty("active_embedding_version", self.active_embedding_version)
        require_non_empty("embedding_model", self.embedding_model)
        require_non_empty("reranker_model", self.reranker_model)

    @property
    def collection_name(self) -> str:
        return f"rag_{self.project_id}_{self.active_embedding_version}"
