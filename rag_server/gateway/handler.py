"""Async gateway core for request validation and enforced retrieval scope."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from rag_server.adapters.base import ProjectAdapter, ProjectAdapterResolver
from rag_server.core.models import BaseProjectConfig, BaseQueryScope, BaseRetrievalFilter


FORBIDDEN_FILTER_KEYS = frozenset(
    {
        "filter",
        "filters",
        "qdrant_filter",
        "raw_filter",
        "raw_qdrant_filter",
    }
)


class GatewayError(Exception):
    """Base class for structured gateway errors."""

    code = "gateway_error"


class InvalidRequestError(GatewayError):
    """Raised when a request fails gateway validation."""

    code = "invalid_request"


class ProjectScopeMismatchError(GatewayError):
    """Raised when an adapter tries to change the enforced request scope."""

    code = "project_scope_mismatch"


class ConcurrencyLimitExceededError(GatewayError):
    """Raised when per-project or per-user concurrency limits are saturated."""

    code = "concurrency_limit_exceeded"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    project_id: str
    user_id: str
    query: str
    kb_ids: tuple[str, ...] = ()
    include_shared: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> SearchRequest:
        _reject_raw_filters(data)
        return cls(
            project_id=_required_str(data, "project_id"),
            user_id=_required_str(data, "user_id"),
            query=_required_str(data, "query"),
            kb_ids=tuple(data.get("kb_ids", ())),
            include_shared=bool(data.get("include_shared", True)),
        )

    def __post_init__(self) -> None:
        _validate_non_empty("project_id", self.project_id)
        _validate_non_empty("user_id", self.user_id)
        _validate_non_empty("query", self.query)
        object.__setattr__(self, "kb_ids", tuple(self.kb_ids))


@dataclass(frozen=True, slots=True)
class IngestRequest:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    source_uri: str
    content_type: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> IngestRequest:
        return cls(
            project_id=_required_str(data, "project_id"),
            user_id=_required_str(data, "user_id"),
            kb_id=_required_str(data, "kb_id"),
            doc_id=_required_str(data, "doc_id"),
            source_uri=_required_str(data, "source_uri"),
            content_type=_required_str(data, "content_type"),
            metadata=dict(data.get("metadata", {})),
        )

    def __post_init__(self) -> None:
        _validate_non_empty("project_id", self.project_id)
        _validate_non_empty("user_id", self.user_id)
        _validate_non_empty("kb_id", self.kb_id)
        _validate_non_empty("doc_id", self.doc_id)
        _validate_non_empty("source_uri", self.source_uri)
        _validate_non_empty("content_type", self.content_type)


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


class AsyncConcurrencyLimiter:
    """Tracks active requests by project and user without blocking the event loop."""

    def __init__(self, *, max_per_project: int, max_per_user: int) -> None:
        if max_per_project <= 0:
            raise ValueError("max_per_project must be positive")
        if max_per_user <= 0:
            raise ValueError("max_per_user must be positive")

        self.max_per_project = max_per_project
        self.max_per_user = max_per_user
        self._lock = asyncio.Lock()
        self._project_counts: dict[str, int] = {}
        self._user_counts: dict[tuple[str, str], int] = {}

    @asynccontextmanager
    async def limit(self, project_id: str, user_id: str) -> AsyncIterator[None]:
        await self._acquire(project_id, user_id)
        try:
            yield
        finally:
            await self._release(project_id, user_id)

    async def _acquire(self, project_id: str, user_id: str) -> None:
        async with self._lock:
            project_count = self._project_counts.get(project_id, 0)
            user_key = (project_id, user_id)
            user_count = self._user_counts.get(user_key, 0)

            if project_count >= self.max_per_project:
                raise ConcurrencyLimitExceededError(
                    f"project concurrency limit exceeded for project_id={project_id!r}"
                )
            if user_count >= self.max_per_user:
                raise ConcurrencyLimitExceededError(
                    "user concurrency limit exceeded for "
                    f"project_id={project_id!r}, user_id={user_id!r}"
                )

            self._project_counts[project_id] = project_count + 1
            self._user_counts[user_key] = user_count + 1

    async def _release(self, project_id: str, user_id: str) -> None:
        async with self._lock:
            user_key = (project_id, user_id)
            self._decrement(self._project_counts, project_id)
            self._decrement(self._user_counts, user_key)

    @staticmethod
    def _decrement(counts: dict[Any, int], key: Any) -> None:
        next_value = counts[key] - 1
        if next_value <= 0:
            del counts[key]
        else:
            counts[key] = next_value


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

            return IngestPlan(
                request=ingest_request,
                adapter=adapter,
                config=config,
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


def _reject_raw_filters(data: dict[str, Any]) -> None:
    forbidden = FORBIDDEN_FILTER_KEYS.intersection(data)
    if forbidden:
        keys = ", ".join(sorted(forbidden))
        raise InvalidRequestError(f"client-supplied retrieval filters are forbidden: {keys}")


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise InvalidRequestError(f"{key} is required")
    _validate_non_empty(key, value)
    return value


def _validate_non_empty(field_name: str, value: str) -> None:
    if not value or not value.strip():
        raise InvalidRequestError(f"{field_name} is required")


def _validate_scope_matches_request(
    scope: BaseQueryScope,
    request: SearchRequest,
) -> None:
    if scope.project_id != request.project_id:
        raise ProjectScopeMismatchError("adapter changed project_id")
    if scope.user_id != request.user_id:
        raise ProjectScopeMismatchError("adapter changed user_id")


def _validate_filter_matches_scope(
    retrieval_filter: BaseRetrievalFilter,
    scope: BaseQueryScope,
) -> None:
    if retrieval_filter.project_id != scope.project_id:
        raise ProjectScopeMismatchError("adapter built filter with different project_id")
    if retrieval_filter.user_id != scope.user_id:
        raise ProjectScopeMismatchError("adapter built filter with different user_id")
