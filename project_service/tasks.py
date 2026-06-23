"""Project-owned task orchestration for project documents."""

from __future__ import annotations

from typing import Any

from project_service.capabilities import (
    ProjectIngestionCapability,
    ProjectRetrievalCapability,
)


class ProjectDocumentTaskService:
    """Manager-facing project-document task executor.

    This service is the project-owned orchestration surface. It owns planning
    and delegates execution through project-facing capability clients.
    """

    def __init__(
        self,
        *,
        planning: Any,
        ingestion: ProjectIngestionCapability,
        retrieval: ProjectRetrievalCapability,
    ) -> None:
        self._planning = planning
        self._ingestion = ingestion
        self._retrieval = retrieval

    async def start_document_ingest_task(self, request: Any) -> Any:
        plan = await self._planning.plan_ingest(request)
        return await self._ingestion.start_ingest(plan)

    async def search_documents(self, request: Any) -> Any:
        plan = await self._planning.plan_search(request)
        return await self._retrieval.search(plan)

    async def get_document_task_status(self, job_id: str) -> Any:
        return await self._ingestion.get_status(job_id)

    async def delete_document(self, request: Any) -> Any:
        plan = await self._planning.plan_delete(request)
        return await self._retrieval.delete_document(plan)

    async def ingest(self, request: Any) -> Any:
        return await self.start_document_ingest_task(request)

    async def search(self, request: Any) -> Any:
        return await self.search_documents(request)

    async def ingest_status(self, job_id: str) -> Any:
        return await self.get_document_task_status(job_id)
