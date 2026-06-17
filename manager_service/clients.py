"""Manager-facing service client protocols."""

from __future__ import annotations

from typing import Any, Protocol

from shared.contracts import IngestJobResult, JobStatus


class IngestionClient(Protocol):
    """Manager-facing contract for ingestion-owned operations."""

    async def ingest(self, request: Any) -> Any:
        ...

    async def ingest_status(self, job_id: str) -> Any:
        ...


class RetrievalClient(Protocol):
    """Manager-facing contract for retrieval-owned operations."""

    async def search(self, request: Any) -> Any:
        ...

    async def delete_document(self, request: Any) -> Any:
        ...


class ProjectDocumentClient(Protocol):
    """Client contract for project-document operations routed by the manager."""

    async def ingest(self, request: Any) -> Any:
        ...

    async def search(self, request: Any) -> Any:
        ...

    async def ingest_status(self, job_id: str) -> Any:
        ...

    async def delete_document(self, request: Any) -> Any:
        ...


class ProjectDocumentIngestionClient:
    """Adapts the compatibility project-document client to ingestion calls."""

    def __init__(self, project_documents: ProjectDocumentClient) -> None:
        self._project_documents = project_documents

    async def ingest(self, request: Any) -> Any:
        return await self._project_documents.ingest(request)

    async def ingest_status(self, job_id: str) -> Any:
        return await self._project_documents.ingest_status(job_id)


class ProjectDocumentRetrievalClient:
    """Adapts the compatibility project-document client to retrieval calls."""

    def __init__(self, project_documents: ProjectDocumentClient) -> None:
        self._project_documents = project_documents

    async def search(self, request: Any) -> Any:
        return await self._project_documents.search(request)

    async def delete_document(self, request: Any) -> Any:
        return await self._project_documents.delete_document(request)


class LocalRetrievalClient:
    """Manager-facing retrieval client backed by a retrieval service object."""

    def __init__(self, retrieval: Any) -> None:
        self._retrieval = retrieval

    async def search(self, request: Any) -> Any:
        return await self._retrieval.search(request)

    async def delete_document(self, request: Any) -> Any:
        return await self._retrieval.delete_document(request)


class LocalIngestionClient:
    """Manager-facing ingestion client backed by local ingestion dependencies."""

    def __init__(self, *, ingestion: Any, jobs: Any) -> None:
        self._ingestion = ingestion
        self._jobs = jobs

    async def ingest(self, request: Any) -> Any:
        return await self._ingestion.ingest(request)

    async def ingest_status(self, job_id: str) -> IngestJobResult:
        job = await self._jobs.get(job_id)
        if job is None:
            return IngestJobResult(job_id=job_id, status=JobStatus.PENDING)
        metadata = dict(getattr(job, "metadata", {}) or {})
        return IngestJobResult(
            job_id=str(getattr(job, "job_id", job_id)),
            status=getattr(job, "status", JobStatus.PENDING),
            doc_id=str(metadata.get("doc_id") or getattr(job, "document_id", "")),
            project_id=str(metadata.get("project_id", "")),
            error=str(getattr(job, "error", "") or ""),
        )
