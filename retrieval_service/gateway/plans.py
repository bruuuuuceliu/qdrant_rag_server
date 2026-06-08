"""Gateway execution plans — assembled DTOs handed from gateway to engine."""

from __future__ import annotations

from dataclasses import dataclass

from retrieval_service.adapters.base import ProjectAdapter
from retrieval_service.core.schemas import (
    BaseProjectConfig,
    BaseQueryScope,
    BaseRetrievalFilter,
)
from retrieval_service.gateway.requests import IngestRequest, SearchRequest


@dataclass(frozen=True, slots=True)
class SearchPlan:
    request: SearchRequest
    adapter: ProjectAdapter
    config: BaseProjectConfig
    scope: BaseQueryScope
    retrieval_filter: BaseRetrievalFilter


@dataclass(frozen=True, slots=True)
class IngestPlan:
    request: IngestRequest
    adapter: ProjectAdapter
    config: BaseProjectConfig
