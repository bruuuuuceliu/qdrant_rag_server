"""Project-RAG configuration schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from project_service.schemas.common import require_non_empty


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectConfig:
    project_id: str
    project_type: str
    service_id: str = ""
    service_type: str = ""
    active_embedding_version: str = ""
    embedding_model: str = ""
    reranker_model: str = ""
    chunker_config: dict[str, Any] = field(default_factory=dict)
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    cache_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("project_id", self.project_id)
        require_non_empty("project_type", self.project_type)
        object.__setattr__(self, "service_id", self.service_id or self.project_id)
        object.__setattr__(self, "service_type", self.service_type or self.project_type)
        require_non_empty("service_id", self.service_id)
        require_non_empty("service_type", self.service_type)
        require_non_empty("active_embedding_version", self.active_embedding_version)
        require_non_empty("embedding_model", self.embedding_model)
        require_non_empty("reranker_model", self.reranker_model)

    @property
    def collection_name(self) -> str:
        return f"rag_{self.project_id}_{self.active_embedding_version}"
