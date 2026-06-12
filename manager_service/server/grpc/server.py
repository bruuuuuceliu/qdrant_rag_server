"""gRPC server whose public API is routed through the manager service."""

from __future__ import annotations

import logging
from typing import Any

import grpc
from grpc import aio

from manager_service.errors import ManagerIngestFailedError
from manager_service.service import ManagerService
from project_service.gateway.requests import IngestRequest, SearchRequest
from project_service.rag.engine import GenerationUnavailableError
from retrieval_service.llm import OpenRouterClientError
from shared.queue import QueueFullError
from project_service.server.grpc.generated import retrieval_service_pb2
from project_service.server.grpc.generated import retrieval_service_pb2_grpc
from project_service.server.grpc.server import _search_result_to_proto

logger = logging.getLogger(__name__)


class ManagerRagServiceServicer(retrieval_service_pb2_grpc.RagServiceServicer):
    """Compatibility RagService implementation routed through manager dispatch."""

    def __init__(
        self,
        *,
        manager: ManagerService,
        generation_engine: Any = None,
        health_checker: Any = None,
    ) -> None:
        self._manager = manager
        self._generation_engine = generation_engine
        self._health_checker = health_checker

    async def Search(
        self,
        request: retrieval_service_pb2.SearchRequest,
        context: grpc.aio.ServicerContext,
    ) -> retrieval_service_pb2.SearchResponse:
        try:
            result = await self._manager.search(
                SearchRequest(
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
        return _search_result_to_proto(result)

    async def Ingest(
        self,
        request: retrieval_service_pb2.IngestRequest,
        context: grpc.aio.ServicerContext,
    ) -> retrieval_service_pb2.IngestResponse:
        try:
            result = await self._manager.ingest(
                IngestRequest(
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
        except QueueFullError as exc:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, str(exc))
        except TimeoutError as exc:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, str(exc))
        except ManagerIngestFailedError as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))
        except Exception:
            logger.exception("manager ingest failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")
        return retrieval_service_pb2.IngestResponse(
            job_id=result.job_id,
            status=result.status.value,
        )

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
        return retrieval_service_pb2.GetIngestJobStatusResponse(
            job_id=result.job_id,
            status=result.status.value,
            error=getattr(result, "error", "") or "",
            doc_id=getattr(result, "doc_id", "") or "",
        )

    async def Generate(
        self,
        request: retrieval_service_pb2.GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> retrieval_service_pb2.GenerateResponse:
        if self._generation_engine is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "generation is unavailable")
        if not request.openrouter_api_key:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "openrouter_api_key is required",
            )

        chunks: list[dict[str, Any]] = [
            {
                "project_id": c.project_id,
                "user_id": c.user_id,
                "kb_id": c.kb_id,
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "chunk_index": c.chunk_index,
                "text": c.text,
                "score": c.score,
            }
            for c in request.chunks
        ]
        try:
            result = await self._generation_engine.generate(
                project_id=request.project_id,
                user_id=request.user_id,
                query=request.query,
                chunks=chunks,
                openrouter_key=request.openrouter_api_key,
                model=request.model or None,
            )
        except GenerationUnavailableError as exc:
            await context.abort(grpc.StatusCode.UNAVAILABLE, str(exc))
        except OpenRouterClientError as exc:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, str(exc))
        except Exception:
            logger.exception("generation failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")

        return retrieval_service_pb2.GenerateResponse(
            response=result.response,
            cache_hit=result.cache_hit,
        )

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


async def serve_grpc(
    *,
    manager: ManagerService,
    generation_engine: Any = None,
    health_checker: Any = None,
    port: int = 50051,
) -> aio.Server:
    server = aio.server()
    servicer = ManagerRagServiceServicer(
        manager=manager,
        generation_engine=generation_engine,
        health_checker=health_checker,
    )
    retrieval_service_pb2_grpc.add_RagServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    logger.info("manager gRPC server starting on port %s", port)
    await server.start()
    return server
