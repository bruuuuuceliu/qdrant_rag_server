"""Local project-service client used during service extraction."""

from __future__ import annotations

from typing import Any

from project_service.gateway.requests import (
    DeleteDocumentRequest,
    IngestRequest,
    SearchRequest,
)


class LocalProjectServiceClient:
    """In-process project-document client.

    It composes gateway planning with engine execution while the project service
    is still deployed in-process.
    """

    def __init__(self, *, gateway: Any, engine: Any) -> None:
        self._gateway = gateway
        self._engine = engine

    async def ingest(self, request: Any) -> Any:
        plan = await self._gateway.prepare_ingest(_ingest_request(request))
        return await self._engine.schedule_ingest(plan)

    async def search(self, request: Any) -> Any:
        plan = await self._gateway.prepare_search(_search_request(request))
        return await self._engine.search(plan)

    async def ingest_status(self, job_id: str) -> Any:
        return await self._engine.get_ingest_status(job_id)

    async def delete_document(self, request: Any) -> Any:
        plan = await self._gateway.prepare_delete(_delete_request(request))
        return await self._engine.delete_document(
            config=plan.config,
            user_id=plan.request.user_id,
            kb_id=plan.request.kb_id,
            doc_id=plan.request.doc_id,
        )


def _ingest_request(request: Any) -> Any:
    if isinstance(request, dict):
        return IngestRequest.from_mapping(request)
    return request


def _search_request(request: Any) -> Any:
    if isinstance(request, dict):
        return SearchRequest.from_mapping(request)
    return request


def _delete_request(request: Any) -> Any:
    if isinstance(request, dict):
        return DeleteDocumentRequest.from_mapping(request)
    return request
