"""Gateway execution plans — assembled DTOs handed from gateway to engine."""

from __future__ import annotations

from dataclasses import dataclass

from project_service.adapters.base import ProjectAdapter
from project_service.schemas import (
    ProjectConfig,
    ProjectQueryScope,
    ProjectRetrievalFilter,
)
from project_service.gateway.requests import IngestRequest, SearchRequest


@dataclass(frozen=True, slots=True)
class SearchPlan:
    request: SearchRequest
    adapter: ProjectAdapter
    config: ProjectConfig
    scope: ProjectQueryScope
    retrieval_filter: ProjectRetrievalFilter


@dataclass(frozen=True, slots=True)
class IngestPlan:
    request: IngestRequest
    adapter: ProjectAdapter
    config: ProjectConfig
