"""Manager-owned gRPC server.

This server translates gRPC proto messages into manager-service calls.
It depends only on shared contracts, manager types, and the generated
proto stubs (which are pure transport code, not business logic).

Compatibility note:
- The generated proto package still lives under project_service until the
  transport package is moved to a neutral shared namespace.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import grpc
from grpc import aio

from manager_service.service import ManagerService, ManagerTaskAccepted
from shared.transport.grpc.generated import retrieval_service_pb2
from shared.transport.grpc.generated import retrieval_service_pb2_grpc
from shared.contracts import TaskStatus, TaskStatusRecord

logger = logging.getLogger(__name__)


class ManagerRagServiceServicer(retrieval_service_pb2_grpc.RagServiceServicer):
    """Compatibility RagService implementation routed through manager dispatch.

    All RPC methods translate proto → manager DTO → proto without importing
    project_service domain types. The only remaining cross-service import is
    the generated proto stubs, which are transport code shared across the
    project.
    """

    def __init__(
        self,
        *,
        manager: ManagerService,
        health_checker: Any = None,
    ) -> None:
        self._manager = manager
        self._health_checker = health_checker

    # -- Search -----------------------------------------------------------

    async def Search(
        self,
        request: retrieval_service_pb2.SearchRequest,
        context: grpc.aio.ServicerContext,
    ) -> retrieval_service_pb2.SearchResponse:
        try:
            result = await self._manager.search(
                _Namespace(
                    project_id=request.project_id,
                    user_id=request.user_id,
                    query=request.query,
                    kb_ids=tuple(request.kb_ids),
                    include_shared=request.include_shared,
                )
            )
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception:
            logger.exception("manager search failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")
        if isinstance(result, TaskStatusRecord):
            return _search_result_to_proto(_search_result_from_task_record(result))
        if isinstance(result, ManagerTaskAccepted):
            result = await self._wait_for_task_result(result.task_id, context)
        return _search_result_to_proto(result)

    # -- Ingest -----------------------------------------------------------

    async def Ingest(
        self,
        request: retrieval_service_pb2.IngestRequest,
        context: grpc.aio.ServicerContext,
    ) -> retrieval_service_pb2.IngestResponse:
        try:
            result = await self._manager.ingest(
                _Namespace(
                    project_id=request.project_id,
                    user_id=request.user_id,
                    kb_id=request.kb_id,
                    doc_id=request.doc_id,
                    source_uri=request.source_uri,
                    content_type=request.content_type,
                    metadata=dict(request.metadata),
                )
            )
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception:
            logger.exception("manager ingest failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")
        status = str(getattr(result, "status", "") or "")
        if not status and bool(getattr(result, "accepted", False)):
            status = TaskStatus.ACCEPTED.value
        return retrieval_service_pb2.IngestResponse(
            job_id=_result_job_id(result),
            status=status,
        )

    # -- Status -----------------------------------------------------------

    async def GetIngestJobStatus(
        self,
        request: retrieval_service_pb2.GetIngestJobStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> retrieval_service_pb2.GetIngestJobStatusResponse:
        try:
            result = await self._manager.ingest_status(request.job_id)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except Exception:
            logger.exception("manager ingest status failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")
        if result is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "job not found")
        result_payload = getattr(result, "result", {}) or {}
        if not isinstance(result_payload, dict):
            result_payload = {}
        doc_id = str(getattr(result, "doc_id", "") or result_payload.get("doc_id", ""))
        if not doc_id:
            doc_id = _ingest_result_doc_id(result_payload)
        return retrieval_service_pb2.GetIngestJobStatusResponse(
            job_id=_result_job_id(result) or request.job_id,
            status=str(getattr(result, "status", "")),
            error=str(getattr(result, "error", "") or result_payload.get("error", "")),
            doc_id=doc_id,
        )

    # -- Generate ---------------------------------------------------------

    async def Generate(
        self,
        request: retrieval_service_pb2.GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> retrieval_service_pb2.GenerateResponse:
        await context.abort(
            grpc.StatusCode.UNIMPLEMENTED,
            "generation is not part of the broker-first manager flow",
        )

    # -- Health -----------------------------------------------------------

    async def HealthCheck(
        self,
        request: retrieval_service_pb2.HealthCheckRequest,
        context: grpc.aio.ServicerContext,
    ) -> retrieval_service_pb2.HealthCheckResponse:
        if self._health_checker is not None:
            report = await self._health_checker.check()
            return retrieval_service_pb2.HealthCheckResponse(
                status=report.status,
                components={c.name: c.message for c in report.components},
            )
        return retrieval_service_pb2.HealthCheckResponse(
            status="healthy",
            components={},
        )

    async def _wait_for_task_result(
        self,
        task_id: str,
        context: grpc.aio.ServicerContext,
    ) -> Any:
        deadline = _grpc_time_remaining(context)
        timeout_seconds = deadline if deadline is not None and deadline > 0 else 30.0
        loop = asyncio.get_running_loop()
        expires_at = loop.time() + timeout_seconds
        last: TaskStatusRecord | None = None
        while True:
            try:
                last = await self._manager.ingest_status(task_id)
            except ValueError as exc:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            except Exception:
                logger.exception("manager task status lookup failed")
                await context.abort(grpc.StatusCode.INTERNAL, "internal error")
            if last is not None:
                if last.status == TaskStatus.COMPLETED.value:
                    return _search_result_from_task_record(last)
                if last.status == TaskStatus.FAILED.value:
                    detail = last.error or str(last.result.get("error", "search task failed"))
                    await context.abort(grpc.StatusCode.INTERNAL, detail)
            if loop.time() >= expires_at:
                detail = f"search task {task_id} did not complete before gRPC deadline"
                await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, detail)
            await asyncio.sleep(min(0.1, max(0.0, expires_at - loop.time())))


# -- Helpers ---------------------------------------------------------------


class _Namespace(SimpleNamespace):
    """Lightweight request DTO passed to ManagerService methods.

    ManagerService reads fields via getattr, so a SimpleNamespace subclass
    suffices — no need to import project_service gateway request types.
    """


def _result_job_id(result: Any) -> str:
    return str(getattr(result, "job_id", "") or getattr(result, "task_id", ""))


def _ingest_result_doc_id(result: dict[str, Any]) -> str:
    helpers = result.get("helpers", {})
    if not isinstance(helpers, dict):
        return ""
    for helper_result in helpers.values():
        if not isinstance(helper_result, dict):
            continue
        for key in ("doc_id", "document_id"):
            value = helper_result.get(key)
            if value:
                return str(value)
        index_request = helper_result.get("index_request", {})
        if isinstance(index_request, dict):
            for collection_key in ("chunks", "payloads"):
                values = index_request.get(collection_key, [])
                if not isinstance(values, list):
                    continue
                for item in values:
                    if not isinstance(item, dict):
                        continue
                    for key in ("document_id", "doc_id"):
                        value = item.get(key)
                        if value:
                            return str(value)
    return ""


def _search_result_to_proto(result: Any) -> retrieval_service_pb2.SearchResponse:
    """Convert a manager search result into the compat proto response.

    Manager-owned copy that does not depend on project_service internal helpers.
    """
    chunks = []
    for c in getattr(result, "chunks", []) or []:
        if isinstance(c, dict):
            chunks.append(
                retrieval_service_pb2.ChunkResult(
                    project_id=str(c.get("project_id", "")),
                    user_id=str(c.get("user_id", "")),
                    kb_id=str(c.get("kb_id", "")),
                    doc_id=str(c.get("doc_id", "")),
                    chunk_id=str(c.get("chunk_id", "")),
                    chunk_index=int(c.get("chunk_index", 0)),
                    text=str(c.get("text", "")),
                    score=float(c.get("score", 0.0)),
                )
            )
        else:
            chunks.append(
                retrieval_service_pb2.ChunkResult(
                    project_id=str(getattr(c, "project_id", "")),
                    user_id=str(getattr(c, "user_id", "")),
                    kb_id=str(getattr(c, "kb_id", "")),
                    doc_id=str(getattr(c, "doc_id", "")),
                    chunk_id=str(getattr(c, "chunk_id", "")),
                    chunk_index=int(getattr(c, "chunk_index", 0)),
                    text=str(getattr(c, "text", "")),
                    score=float(getattr(c, "score", 0.0)),
                )
            )
    return retrieval_service_pb2.SearchResponse(
        chunks=chunks,
        elapsed_ms=int(getattr(result, "elapsed_ms", 0)),
        cache_hit=bool(getattr(result, "cache_hit", False)),
    )


def _search_result_from_task_record(record: TaskStatusRecord) -> SimpleNamespace:
    result = dict(record.result)
    if isinstance(result.get("result"), dict):
        result = dict(result["result"])
    chunks = result.get("chunks")
    if not isinstance(chunks, list):
        chunks = result.get("hits")
    if not isinstance(chunks, list):
        chunks = []
    return SimpleNamespace(
        chunks=[dict(chunk) for chunk in chunks if isinstance(chunk, dict)],
        elapsed_ms=int(result.get("elapsed_ms", 0) or 0),
        cache_hit=bool(result.get("cache_hit", False)),
    )


def _grpc_time_remaining(context: grpc.aio.ServicerContext) -> float | None:
    time_remaining = getattr(context, "time_remaining", None)
    if time_remaining is None:
        return None
    value = time_remaining()
    return float(value) if value is not None else None


async def serve_grpc(
    *,
    manager: ManagerService,
    health_checker: Any = None,
    port: int = 50051,
) -> aio.Server:
    server = aio.server()
    servicer = ManagerRagServiceServicer(
        manager=manager,
        health_checker=health_checker,
    )
    retrieval_service_pb2_grpc.add_RagServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    logger.info("manager gRPC server starting on port %s", port)
    await server.start()
    return server
