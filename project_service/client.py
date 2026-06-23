"""Project-service clients used during service extraction."""

from __future__ import annotations

import inspect
from typing import Any

import grpc

from project_service.capabilities import (
    CompatibilityIngestionCapability,
    CompatibilityRetrievalCapability,
    ProjectIngestionCapability,
    ProjectRetrievalCapability,
)
from project_service.gateway.requests import (
    DeleteDocumentRequest,
    IngestRequest,
    SearchRequest,
)
from project_service.schemas import IngestResult, SearchResult
from project_service.server.grpc.generated import retrieval_service_pb2
from project_service.server.grpc.generated import retrieval_service_pb2_grpc
from project_service.planning import ProjectPlanningService
from project_service.tasks import ProjectDocumentTaskService
from retrieval_service.core.schemas import JobStatus
from retrieval_service.retrieval import (
    DeleteDocumentRequest as RetrievalDeleteDocumentRequest,
    RetrievalSearchRequest,
)


class LocalProjectServiceClient:
    """In-process project-document client.

    It composes gateway planning with engine execution while the project service
    is still deployed in-process.
    """

    def __init__(
        self,
        *,
        gateway: Any,
        engine: Any,
        retrieval_executor: Any | None = None,
        planning: Any | None = None,
        ingestion: ProjectIngestionCapability | None = None,
        retrieval: ProjectRetrievalCapability | None = None,
    ) -> None:
        self._gateway = gateway
        self._engine = engine
        ingestion = ingestion or CompatibilityIngestionCapability(engine)
        retrieval = retrieval or CompatibilityRetrievalCapability(
            retrieval_executor or engine,
        )
        self._tasks = ProjectDocumentTaskService(
            planning=planning or ProjectPlanningService(gateway=gateway),
            ingestion=ingestion,
            retrieval=retrieval,
        )

    async def ingest(self, request: Any) -> Any:
        return await self.start_document_ingest_task(request)

    async def start_document_ingest_task(self, request: Any) -> Any:
        return await self._tasks.start_document_ingest_task(request)

    async def search(self, request: Any) -> Any:
        return await self.search_documents(request)

    async def search_documents(self, request: Any) -> Any:
        return await self._tasks.search_documents(request)

    async def ingest_status(self, job_id: str) -> Any:
        return await self.get_document_task_status(job_id)

    async def get_document_task_status(self, job_id: str) -> Any:
        return await self._tasks.get_document_task_status(job_id)

    async def delete_document(self, request: Any) -> Any:
        return await self._tasks.delete_document(request)


class ProjectPlannedRetrievalClient:
    """Retrieval client using project planning and retrieval-owned execution."""

    def __init__(self, *, gateway: Any, retrieval_service: Any) -> None:
        self._planning = ProjectPlanningService(gateway=gateway)
        self._retrieval_service = retrieval_service

    async def search(self, request: Any) -> SearchResult:
        plan = await self._planning.plan_search(request)
        result = await self._retrieval_service.search(
            RetrievalSearchRequest(
                project_id=plan.project_id,
                user_id=plan.user_id,
                query_text=plan.query_text,
                collection_name=plan.collection_name,
                retrieval_config=dict(plan.retrieval_config),
                retrieval_filter=plan.retrieval_filter,
                placement_plan=dict(plan.placement_plan),
            )
        )
        return SearchResult(
            chunks=result.chunks,
            elapsed_ms=result.elapsed_ms,
            cache_hit=result.cache_hit,
        )

    async def delete_document(self, request: Any) -> None:
        plan = await self._planning.plan_delete(request)
        await self._retrieval_service.delete_document(
            RetrievalDeleteDocumentRequest(
                project_id=plan.project_id,
                user_id=plan.user_id,
                kb_id=plan.kb_id,
                doc_id=plan.doc_id,
                collection_name=plan.collection_name,
                placement_plan=dict(plan.placement_plan),
            )
        )


class ProjectPlannedRetrievalApiClient:
    """Retrieval client using project planning and retrieval API execution."""

    def __init__(
        self,
        *,
        retrieval_api: Any,
        planning: Any | None = None,
        gateway: Any | None = None,
    ) -> None:
        if planning is None:
            if gateway is None:
                raise ValueError("ProjectPlannedRetrievalApiClient requires planning")
            planning = ProjectPlanningService(gateway=gateway)
        self._planning = planning
        self._retrieval_api = retrieval_api

    async def search(self, request: Any) -> SearchResult:
        plan = await self._planning.plan_search(request)
        request_id = _request_id("search", plan)
        response = await _call_retrieval_api(
            self._retrieval_api.search,
            {
                "request_id": request_id,
                "request": {
                    "project_id": plan.project_id,
                    "user_id": plan.user_id,
                    "query_text": plan.query_text,
                    "collection_name": plan.collection_name,
                    "retrieval_config": dict(plan.retrieval_config),
                    "retrieval_filter": plan.retrieval_filter,
                    "placement_plan": dict(plan.placement_plan),
                },
            },
            fallback_request_id=request_id,
        )
        result = _ensure_ok(response)
        return SearchResult(
            chunks=[dict(chunk) for chunk in result.get("chunks", [])],
            elapsed_ms=int(result.get("elapsed_ms", 0)),
            cache_hit=bool(result.get("cache_hit", False)),
        )

    async def delete_document(self, request: Any) -> None:
        plan = await self._planning.plan_delete(request)
        request_id = _request_id("delete", plan)
        response = await _call_retrieval_api(
            self._retrieval_api.delete_document,
            {
                "request_id": request_id,
                "request": {
                    "project_id": plan.project_id,
                    "user_id": plan.user_id,
                    "kb_id": plan.kb_id,
                    "doc_id": plan.doc_id,
                    "collection_name": plan.collection_name,
                    "placement_plan": dict(plan.placement_plan),
                },
            },
            fallback_request_id=request_id,
        )
        _ensure_ok(response)
        return None


class RemoteProjectServiceClient:
    """gRPC project-document client for a separately running project service."""

    def __init__(
        self,
        *,
        target: str,
        stub: Any | None = None,
        channel: grpc.aio.Channel | None = None,
    ) -> None:
        if stub is None and channel is not None:
            stub = retrieval_service_pb2_grpc.RagServiceStub(channel)
        if stub is None:
            channel = grpc.aio.insecure_channel(target)
            stub = retrieval_service_pb2_grpc.RagServiceStub(channel)
        self._target = target
        self._channel = channel
        self._stub = stub

    async def shutdown(self) -> None:
        if self._channel is not None:
            await self._channel.close()

    async def ingest(self, request: Any) -> IngestResult:
        request = _ingest_request(request)
        response = await self._stub.Ingest(_ingest_request_to_proto(request))
        return IngestResult(
            job_id=response.job_id,
            status=_job_status(response.status),
            doc_id=request.doc_id,
            project_id=request.project_id,
            user_id=request.user_id,
            kb_id=request.kb_id,
            data_type=str(request.metadata.get("data_type", "project_document")),
        )

    async def search(self, request: Any) -> SearchResult:
        request = _search_request(request)
        response = await self._stub.Search(
            retrieval_service_pb2.SearchRequest(
                project_id=request.project_id,
                user_id=request.user_id,
                query=request.query,
                kb_ids=list(request.kb_ids),
                include_shared=request.include_shared,
            )
        )
        return SearchResult(
            chunks=[_chunk_result_to_mapping(chunk) for chunk in response.chunks],
            elapsed_ms=response.elapsed_ms,
            cache_hit=response.cache_hit,
        )

    async def ingest_status(self, job_id: str) -> IngestResult | None:
        try:
            response = await self._stub.GetIngestJobStatus(
                retrieval_service_pb2.GetIngestJobStatusRequest(job_id=job_id)
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.NOT_FOUND:
                return None
            raise
        return IngestResult(
            job_id=response.job_id,
            status=_job_status(response.status),
            doc_id=response.doc_id,
            error=response.error or None,
        )

    async def delete_document(self, request: Any) -> Any:
        raise NotImplementedError(
            "remote project delete is not available until the project-service "
            "gRPC contract adds DeleteDocument"
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


def _ensure_ok(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("ok") is True:
        result = response.get("result")
        return dict(result) if isinstance(result, dict) else {}
    error = response.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "retrieval_error")
        message = str(error.get("message") or "retrieval request failed")
        raise RuntimeError(f"{code}: {message}")
    raise RuntimeError("retrieval_error: retrieval request failed")


async def _call_retrieval_api(
    method: Any,
    payload: dict[str, Any],
    *,
    fallback_request_id: str,
) -> dict[str, Any]:
    signature = inspect.signature(method)
    if "fallback_request_id" in signature.parameters:
        return await method(payload, fallback_request_id=fallback_request_id)
    return await method(payload)


def _request_id(prefix: str, plan: Any) -> str:
    request = plan.request
    parts = [
        prefix,
        str(getattr(plan, "project_id", getattr(request, "project_id", ""))),
        str(getattr(plan, "user_id", getattr(request, "user_id", ""))),
        str(getattr(plan, "kb_id", getattr(request, "kb_id", ""))),
        str(getattr(plan, "doc_id", getattr(request, "doc_id", ""))),
    ]
    return ":".join(part for part in parts if part)


def _ingest_request_to_proto(request: Any) -> retrieval_service_pb2.IngestRequest:
    metadata = dict(getattr(request, "metadata", {}) or {})
    raw_text = getattr(request, "raw_text", None)
    raw_content = getattr(request, "raw_content", None)
    if raw_text is not None:
        metadata["raw_text"] = str(raw_text)
    if raw_content is not None:
        if isinstance(raw_content, (bytes, bytearray)):
            metadata["raw_content"] = bytes(raw_content).decode(
                "utf-8",
                errors="replace",
            )
        else:
            metadata["raw_content"] = str(raw_content)
    return retrieval_service_pb2.IngestRequest(
        project_id=request.project_id,
        user_id=request.user_id,
        kb_id=request.kb_id,
        doc_id=request.doc_id,
        source_uri=request.source_uri,
        content_type=request.content_type,
        metadata=metadata,
    )


def _chunk_result_to_mapping(chunk: Any) -> dict[str, Any]:
    result = {
        "project_id": chunk.project_id,
        "user_id": chunk.user_id,
        "kb_id": chunk.kb_id,
        "doc_id": chunk.doc_id,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "score": chunk.score,
    }
    metadata = dict(getattr(chunk, "metadata", {}) or {})
    if metadata:
        result["metadata"] = metadata
    return result


def _job_status(value: str) -> JobStatus:
    try:
        return JobStatus(value)
    except ValueError:
        return JobStatus.PENDING
