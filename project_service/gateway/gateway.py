"""RagGateway — validates requests, enforces scope, and assembles execution plans."""

from __future__ import annotations

from typing import Any

from project_service.adapters.base import ProjectAdapterResolver
from project_service.gateway.errors import (
    InvalidRequestError,
    ProjectScopeMismatchError,
)
from project_service.gateway.limiter import AsyncConcurrencyLimiter
from project_service.gateway.plans import IngestPlan, SearchPlan
from project_service.gateway.requests import IngestRequest, SearchRequest
from project_service.schemas import ProjectQueryScope, ProjectRetrievalFilter


class RagGateway:
    """Async gateway core used by transport layers such as gRPC."""

    def __init__(
        self,
        *,
        adapter_resolver: ProjectAdapterResolver,
        concurrency_limiter: AsyncConcurrencyLimiter,
    ) -> None:
        self._adapter_resolver = adapter_resolver
        self._concurrency_limiter = concurrency_limiter

    async def prepare_search(
        self, request: SearchRequest | dict[str, Any]
    ) -> SearchPlan:
        search_request = _coerce_search_request(request)
        async with self._concurrency_limiter.limit(
            search_request.project_id,
            search_request.user_id,
        ):
            adapter = await self._adapter_resolver.resolve(search_request.project_id)
            config = await adapter.get_config(search_request.project_id)
            scope = await adapter.build_query_scope(search_request)
            _validate_scope_matches_request(scope, search_request)
            retrieval_filter = await adapter.build_retrieval_filter(scope)
            _validate_filter_matches_scope(retrieval_filter, scope)

            return SearchPlan(
                request=search_request,
                adapter=adapter,
                config=config,
                scope=scope,
                retrieval_filter=retrieval_filter,
            )

    async def prepare_ingest(
        self, request: IngestRequest | dict[str, Any]
    ) -> IngestPlan:
        ingest_request = _coerce_ingest_request(request)
        async with self._concurrency_limiter.limit(
            ingest_request.project_id,
            ingest_request.user_id,
        ):
            adapter = await self._adapter_resolver.resolve(ingest_request.project_id)
            config = await adapter.get_config(ingest_request.project_id)
            ingester = await adapter.select_ingester(
                ingest_request,
                config=config,
            )

            return IngestPlan(
                request=ingest_request,
                adapter=adapter,
                config=config,
                ingester=ingester,
            )


def _coerce_search_request(request: SearchRequest | dict[str, Any]) -> SearchRequest:
    if isinstance(request, SearchRequest):
        return request
    if isinstance(request, dict):
        return SearchRequest.from_mapping(request)
    raise InvalidRequestError("search request must be SearchRequest or mapping")


def _coerce_ingest_request(request: IngestRequest | dict[str, Any]) -> IngestRequest:
    if isinstance(request, IngestRequest):
        return request
    if isinstance(request, dict):
        return IngestRequest.from_mapping(request)
    raise InvalidRequestError("ingest request must be IngestRequest or mapping")


def _validate_scope_matches_request(
    scope: ProjectQueryScope,
    request: SearchRequest,
) -> None:
    if scope.project_id != request.project_id:
        raise ProjectScopeMismatchError("adapter changed project_id")
    if scope.user_id != request.user_id:
        raise ProjectScopeMismatchError("adapter changed user_id")


def _validate_filter_matches_scope(
    retrieval_filter: ProjectRetrievalFilter,
    scope: ProjectQueryScope,
) -> None:
    if retrieval_filter.project_id != scope.project_id:
        raise ProjectScopeMismatchError("adapter built filter with different project_id")
    if retrieval_filter.user_id != scope.user_id:
        raise ProjectScopeMismatchError("adapter built filter with different user_id")
