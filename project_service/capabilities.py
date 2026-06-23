"""Project-service capability client contracts and local adapters."""

from __future__ import annotations

from typing import Any, Protocol


class ProjectIngestionCapability(Protocol):
    """Project-facing ingestion capability."""

    async def start_ingest(self, plan: Any) -> Any:
        ...

    async def get_status(self, job_id: str) -> Any:
        ...


class ProjectRetrievalCapability(Protocol):
    """Project-facing retrieval/database capability."""

    async def search(self, plan: Any) -> Any:
        ...

    async def delete_document(self, plan: Any) -> Any:
        ...


class CompatibilityIngestionCapability:
    """Adapter over the temporary compatibility ingest executor."""

    def __init__(self, executor: Any, *, status_reader: Any | None = None) -> None:
        self._executor = executor
        self._status_reader = status_reader or executor

    async def start_ingest(self, plan: Any) -> Any:
        return await self._executor.schedule_ingest(plan.raw_plan)

    async def get_status(self, job_id: str) -> Any:
        get_status = getattr(self._status_reader, "get_document_task_status", None)
        if get_status is not None:
            return await get_status(job_id)
        return await self._status_reader.get_ingest_status(job_id)


class CompatibilityRetrievalCapability:
    """Adapter over temporary compatibility retrieval executors."""

    def __init__(self, executor: Any) -> None:
        self._executor = executor

    async def search(self, plan: Any) -> Any:
        search_documents = getattr(self._executor, "search_documents", None)
        if search_documents is not None:
            return await search_documents(plan)
        return await self._executor.search(plan.raw_plan)

    async def delete_document(self, plan: Any) -> Any:
        delete_document = getattr(self._executor, "delete_project_document", None)
        if delete_document is not None:
            return await delete_document(plan)
        return await self._executor.delete_document(
            config=plan.raw_plan.config,
            user_id=plan.user_id,
            kb_id=plan.kb_id,
            doc_id=plan.doc_id,
        )
