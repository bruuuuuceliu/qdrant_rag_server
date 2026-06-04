"""Async gRPC server for the RAG service."""

from __future__ import annotations

import logging
from typing import Any

import grpc
from grpc import aio

from rag_server.engine.engine import RagEngine, SearchResult, GenerateResult
from rag_server.gateway.handler import (
    GatewayError,
    IngestRequest,
    RagGateway,
    SearchRequest,
)
from rag_server.services.generation import OpenRouterClientError
from rag_server.health.health import HealthChecker
from rag_server.grpc import rag_service_pb2
from rag_server.grpc import rag_service_pb2_grpc

logger = logging.getLogger(__name__)


class RagServiceServicer(rag_service_pb2_grpc.RagServiceServicer):
    """Async gRPC servicer delegating to the RAG gateway and engine."""

    def __init__(
        self,
        *,
        gateway: RagGateway,
        engine: RagEngine,
        health_checker: HealthChecker | None = None,
    ) -> None:
        self._gateway = gateway
        self._engine = engine
        self._health_checker = health_checker

    async def Search(
        self,
        request: rag_service_pb2.SearchRequest,
        context: grpc.aio.ServicerContext,
    ) -> rag_service_pb2.SearchResponse:
        try:
            plan = await self._gateway.prepare_search(
                SearchRequest(
                    project_id=request.project_id,
                    user_id=request.user_id,
                    query=request.query,
                    kb_ids=tuple(request.kb_ids),
                    include_shared=request.include_shared,
                )
            )
        except GatewayError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, exc.args[0])
        except Exception:
            logger.exception("search preparation failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")

        try:
            result = await self._engine.search(plan)
        except Exception:
            logger.exception("search execution failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")

        return _search_result_to_proto(result)

    async def Ingest(
        self,
        request: rag_service_pb2.IngestRequest,
        context: grpc.aio.ServicerContext,
    ) -> rag_service_pb2.IngestResponse:
        try:
            plan = await self._gateway.prepare_ingest(
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
        except GatewayError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, exc.args[0])
        except Exception:
            logger.exception("ingest preparation failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")

        try:
            result = await self._engine.schedule_ingest(plan)
        except Exception:
            logger.exception("ingest scheduling failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")

        return rag_service_pb2.IngestResponse(
            job_id=result.job_id,
            status=result.status.value,
        )

    async def GetIngestJobStatus(
        self,
        request: rag_service_pb2.GetIngestJobStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> rag_service_pb2.GetIngestJobStatusResponse:
        result = await self._engine.get_ingest_status(request.job_id)
        if result is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "job not found")

        return rag_service_pb2.GetIngestJobStatusResponse(
            job_id=result.job_id,
            status=result.status.value,
            error=getattr(result, "error", "") or "",
            doc_id=getattr(result, "doc_id", "") or "",
        )

    async def Generate(
        self,
        request: rag_service_pb2.GenerateRequest,
        context: grpc.aio.ServicerContext,
    ) -> rag_service_pb2.GenerateResponse:
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
            result = await self._engine.generate(
                project_id=request.project_id,
                user_id=request.user_id,
                query=request.query,
                chunks=chunks,
                openrouter_key=request.openrouter_api_key,
                model=request.model or None,
            )
        except OpenRouterClientError as exc:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, str(exc))
        except Exception:
            logger.exception("generation failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")

        return rag_service_pb2.GenerateResponse(
            response=result.response,
            cache_hit=result.cache_hit,
        )

    async def HealthCheck(
        self,
        request: rag_service_pb2.HealthCheckRequest,
        context: grpc.aio.ServicerContext,
    ) -> rag_service_pb2.HealthCheckResponse:
        if self._health_checker is not None:
            report = await self._health_checker.check()
            components: dict[str, str] = {
                c.name: c.message for c in report.components
            }
            return rag_service_pb2.HealthCheckResponse(
                status=report.status,
                components=components,
            )
        return rag_service_pb2.HealthCheckResponse(
            status="healthy",
            components={},
        )


def _search_result_to_proto(result: SearchResult) -> rag_service_pb2.SearchResponse:
    chunks = [
        rag_service_pb2.ChunkResult(
            project_id=chunk.get("project_id", ""),
            user_id=chunk.get("user_id", ""),
            kb_id=chunk.get("kb_id", ""),
            doc_id=chunk.get("doc_id", ""),
            chunk_id=chunk.get("chunk_id", ""),
            chunk_index=int(chunk.get("chunk_index", 0)),
            text=chunk.get("text", ""),
            score=float(chunk.get("score", 0.0)),
        )
        for chunk in result.chunks
    ]
    return rag_service_pb2.SearchResponse(
        chunks=chunks,
        elapsed_ms=result.elapsed_ms,
        cache_hit=result.cache_hit,
    )


async def serve_grpc(
    *,
    gateway: RagGateway,
    engine: RagEngine,
    port: int = 50051,
) -> aio.Server:
    server = aio.server()
    servicer = RagServiceServicer(gateway=gateway, engine=engine)
    rag_service_pb2_grpc.add_RagServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    logger.info("gRPC server starting on port %s", port)
    await server.start()
    return server
