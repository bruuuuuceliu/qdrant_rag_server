"""Project-owned planning API for domain task orchestration.

This module exposes project config/scope decisions without requiring callers to
reach into gateway internals or the compatibility ``RagEngine``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_service.gateway.requests import (
    DeleteDocumentRequest,
    IngestRequest,
    SearchRequest,
)


@dataclass(frozen=True, slots=True)
class ProjectSearchPlan:
    raw_plan: Any
    request: SearchRequest
    project_id: str
    user_id: str
    query_text: str
    collection_name: str
    retrieval_config: dict[str, Any]
    retrieval_filter: Any
    placement_plan: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProjectDeletePlan:
    raw_plan: Any
    request: DeleteDocumentRequest
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    collection_name: str
    placement_plan: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProjectIngestPlan:
    raw_plan: Any
    request: IngestRequest
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    collection_name: str
    retrieval_config: dict[str, Any]
    chunker_config: dict[str, Any]
    placement_plan: dict[str, Any]


class ProjectPlanningService:
    """Project-owned config/scope planning facade."""

    def __init__(
        self,
        *,
        gateway: Any,
        placement_resolver: Any | None = None,
        routing_policy: Any | None = None,
    ) -> None:
        self._gateway = gateway
        self._placement_resolver = placement_resolver
        self._routing_policy = routing_policy

    async def plan_search(self, request: Any) -> ProjectSearchPlan:
        plan = await self._gateway.prepare_search(_search_request(request))
        return ProjectSearchPlan(
            raw_plan=plan,
            request=plan.request,
            project_id=plan.config.project_id,
            user_id=plan.request.user_id,
            query_text=plan.request.query,
            collection_name=plan.config.collection_name,
            retrieval_config=dict(plan.config.retrieval_config),
            retrieval_filter=plan.retrieval_filter,
            placement_plan=self._resolve_placement(
                operation="read",
                project_id=plan.config.project_id,
                user_id=plan.request.user_id,
                collection_name=plan.config.collection_name,
                request=plan.request,
            ),
        )

    async def plan_delete(self, request: Any) -> ProjectDeletePlan:
        plan = await self._gateway.prepare_delete(_delete_request(request))
        return ProjectDeletePlan(
            raw_plan=plan,
            request=plan.request,
            project_id=plan.config.project_id,
            user_id=plan.request.user_id,
            kb_id=plan.request.kb_id,
            doc_id=plan.request.doc_id,
            collection_name=plan.config.collection_name,
            placement_plan=self._resolve_placement(
                operation="write",
                project_id=plan.config.project_id,
                user_id=plan.request.user_id,
                collection_name=plan.config.collection_name,
                request=plan.request,
            ),
        )

    async def plan_ingest(self, request: Any) -> ProjectIngestPlan:
        plan = await self._gateway.prepare_ingest(_ingest_request(request))
        return ProjectIngestPlan(
            raw_plan=plan,
            request=plan.request,
            project_id=plan.config.project_id,
            user_id=plan.request.user_id,
            kb_id=plan.request.kb_id,
            doc_id=plan.request.doc_id,
            collection_name=plan.config.collection_name,
            retrieval_config=dict(plan.config.retrieval_config),
            chunker_config=dict(plan.config.chunker_config),
            placement_plan=self._resolve_placement(
                operation="write",
                project_id=plan.config.project_id,
                user_id=plan.request.user_id,
                collection_name=plan.config.collection_name,
                request=plan.request,
            ),
        )

    def _resolve_placement(
        self,
        *,
        operation: str,
        project_id: str,
        user_id: str,
        collection_name: str,
        request: Any,
    ) -> dict[str, Any]:
        if self._placement_resolver is None:
            return {}

        from retrieval_service.placement import ProjectPlacementScope

        scope = ProjectPlacementScope(
            project_id=project_id,
            user_id=user_id,
            topic_id=_topic_id(request),
            doc_id=str(getattr(request, "doc_id", "")),
        )
        if self._routing_policy is None:
            if operation == "read":
                plan = self._placement_resolver.resolve_project_read(
                    scope=scope,
                    collection_name=collection_name,
                )
            else:
                plan = self._placement_resolver.resolve_project_write(
                    scope=scope,
                    collection_name=collection_name,
                )
        elif operation == "read":
            plan = self._placement_resolver.resolve_read(
                scope=scope,
                policy=self._routing_policy,
                collection_name=collection_name,
            )
        else:
            plan = self._placement_resolver.resolve_write(
                scope=scope,
                policy=self._routing_policy,
                collection_name=collection_name,
            )
        return plan.to_mapping()


def _search_request(request: Any) -> SearchRequest:
    if isinstance(request, SearchRequest):
        return request
    if isinstance(request, dict):
        return SearchRequest.from_mapping(request)
    return request


def _delete_request(request: Any) -> DeleteDocumentRequest:
    if isinstance(request, DeleteDocumentRequest):
        return request
    if isinstance(request, dict):
        return DeleteDocumentRequest.from_mapping(request)
    return request


def _ingest_request(request: Any) -> IngestRequest:
    if isinstance(request, IngestRequest):
        return request
    if isinstance(request, dict):
        return IngestRequest.from_mapping(request)
    return request


def _topic_id(request: Any) -> str:
    value = getattr(request, "topic_id", "")
    if value:
        return str(value)
    metadata = getattr(request, "metadata", {}) or {}
    if isinstance(metadata, dict):
        return str(metadata.get("topic_id", ""))
    return ""
