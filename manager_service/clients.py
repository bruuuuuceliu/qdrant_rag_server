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


class IngestionApiStatusClient:
    """Ingestion client that reads status through the ingestion API boundary."""

    def __init__(self, *, ingestion: Any, api: Any) -> None:
        self._ingestion = ingestion
        self._api = api

    async def ingest(self, request: Any) -> Any:
        return await self._ingestion.ingest(request)

    async def ingest_status(self, job_id: str) -> IngestJobResult:
        response = await self._api.get_status(
            {
                "request_id": f"status:{job_id}",
                "request": {"job_id": job_id},
            },
            fallback_request_id=f"status:{job_id}",
        )
        if response.get("ok") is True:
            result = response.get("result")
            job = result.get("job") if isinstance(result, dict) else {}
            return _ingest_job_result_from_api_job(job, fallback_job_id=job_id)
        error = response.get("error")
        if isinstance(error, dict) and error.get("code") == "not_found":
            return IngestJobResult(job_id=job_id, status=JobStatus.PENDING)
        if isinstance(error, dict):
            code = str(error.get("code") or "ingestion_error")
            message = str(error.get("message") or "ingestion status request failed")
            raise RuntimeError(f"{code}: {message}")
        raise RuntimeError("ingestion_error: ingestion status request failed")


def _ingest_job_result_from_api_job(
    job: Any,
    *,
    fallback_job_id: str,
) -> IngestJobResult:
    if not isinstance(job, dict):
        return IngestJobResult(job_id=fallback_job_id, status=JobStatus.PENDING)
    raw_status = str(job.get("status", JobStatus.PENDING.value))
    try:
        status = JobStatus(raw_status)
    except ValueError:
        status = JobStatus.PENDING
    metadata = job.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return IngestJobResult(
        job_id=str(job.get("job_id") or fallback_job_id),
        status=status,
        doc_id=str(metadata.get("doc_id") or job.get("doc_id", "")),
        project_id=str(metadata.get("project_id", "")),
        error=str(job.get("error") or ""),
    )
