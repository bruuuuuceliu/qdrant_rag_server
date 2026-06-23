"""Thin manager facade over the project-service task boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from typing import Any

from manager_service.clients import ProjectDocumentClient
from manager_service.routing import DataType, ManagerRouter, Operation, RouteRequest


@dataclass(frozen=True, slots=True)
class ManagerRequestContext:
    """Auth/customer context forwarded by manager without owning policy."""

    request_id: str = ""
    auth_context: dict[str, Any] = field(default_factory=dict)
    customer_context: dict[str, Any] = field(default_factory=dict)
    placement_hint: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "auth_context": dict(self.auth_context),
            "customer_context": dict(self.customer_context),
            "placement_hint": dict(self.placement_hint),
        }


class ManagerService:
    """Coordinates public operations through service-owned boundaries."""

    def __init__(
        self,
        *,
        project_documents: ProjectDocumentClient,
        ingest_topic: str = "ingestion.requests",
        ingest_response_timeout: float = 30.0,
        router: ManagerRouter | None = None,
    ) -> None:
        if project_documents is None:
            raise ValueError("ManagerService requires a project-document client")
        self._project_documents = project_documents
        self._ingest_topic = ingest_topic
        self._ingest_response_timeout = ingest_response_timeout
        self._router = router or ManagerRouter()

    async def ingest(
        self,
        request: Any,
        *,
        context: ManagerRequestContext | None = None,
    ) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.INGEST,
                data_type=_data_type(request),
                project_id=_request_str(request, "project_id"),
                user_id=_request_str(request, "user_id"),
                kb_id=_request_str(request, "kb_id"),
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        return await _project_ingest(self._project_documents, request, context=context)

    async def search(
        self,
        request: Any,
        *,
        context: ManagerRequestContext | None = None,
    ) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.SEARCH,
                data_type=_data_type(request),
                project_id=_request_str(request, "project_id"),
                user_id=_request_str(request, "user_id"),
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        return await _project_search(self._project_documents, request, context=context)

    async def ingest_status(
        self,
        job_id: str,
        *,
        data_type: str = DataType.PROJECT_DOCUMENT,
        context: ManagerRequestContext | None = None,
    ) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.STATUS,
                data_type=data_type,
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        return await _project_ingest_status(
            self._project_documents,
            job_id,
            context=context,
        )

    async def delete(
        self,
        request: Any,
        *,
        context: ManagerRequestContext | None = None,
    ) -> Any:
        route = self._router.route(
            RouteRequest(
                operation=Operation.DELETE,
                data_type=_data_type(request),
                project_id=_request_str(request, "project_id"),
                user_id=_request_str(request, "user_id"),
                kb_id=_request_str(request, "kb_id"),
            )
        )
        if not route.executable:
            raise ValueError(route.reason)
        return await _call_project(
            self._project_documents,
            "delete_document",
            request,
            context=context,
        )


def _data_type(request: Any) -> str:
    if isinstance(request, dict):
        metadata = request.get("metadata", {})
    else:
        metadata = getattr(request, "metadata", {})
    metadata = metadata or {}
    value = metadata.get("data_type") if isinstance(metadata, dict) else None
    return str(value or DataType.PROJECT_DOCUMENT)


def _request_str(request: Any, field: str) -> str:
    if isinstance(request, dict):
        return str(request.get(field, ""))
    return str(getattr(request, field, ""))


async def _project_ingest(
    project_documents: ProjectDocumentClient,
    request: Any,
    *,
    context: ManagerRequestContext | None = None,
) -> Any:
    start_task = getattr(project_documents, "start_document_ingest_task", None)
    if start_task is not None:
        return await _call_project_method(start_task, request, context=context)
    return await _call_project_method(project_documents.ingest, request, context=context)


async def _project_search(
    project_documents: ProjectDocumentClient,
    request: Any,
    *,
    context: ManagerRequestContext | None = None,
) -> Any:
    search_documents = getattr(project_documents, "search_documents", None)
    if search_documents is not None:
        return await _call_project_method(search_documents, request, context=context)
    return await _call_project_method(project_documents.search, request, context=context)


async def _project_ingest_status(
    project_documents: ProjectDocumentClient,
    job_id: str,
    *,
    context: ManagerRequestContext | None = None,
) -> Any:
    get_status = getattr(project_documents, "get_document_task_status", None)
    if get_status is not None:
        return await _call_project_method(get_status, job_id, context=context)
    return await _call_project_method(project_documents.ingest_status, job_id, context=context)


async def _call_project(
    project_documents: ProjectDocumentClient,
    method_name: str,
    *args: Any,
    context: ManagerRequestContext | None = None,
) -> Any:
    method = getattr(project_documents, method_name)
    return await _call_project_method(method, *args, context=context)


async def _call_project_method(
    method: Any,
    *args: Any,
    context: ManagerRequestContext | None = None,
) -> Any:
    if context is None:
        return await method(*args)
    if _accepts_context(method):
        return await method(*args, context=context.to_payload())
    return await method(*args)


def _accepts_context(method: Any) -> bool:
    signature = inspect.signature(method)
    if "context" in signature.parameters:
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
