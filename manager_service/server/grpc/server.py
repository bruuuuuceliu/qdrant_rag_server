"""Manager-owned gRPC server.

This server translates gRPC proto messages into manager-service calls.
It depends only on shared contracts, manager types, and the generated
proto stubs (which are pure transport code, not business logic).

Compatibility notes (temporary):
- The proto definition (service RagService) is still shared with the
  project_service compat layer. This will be replaced with a manager-native
  proto after service extraction is complete.
- The Generate RPC delegates directly to the generation engine until
  generation is extracted into its own service boundary.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import grpc
from grpc import aio

from manager_service.errors import ManagerIngestFailedError, ManagerIngestTimeoutError
from manager_service.service import ManagerService
from project_service.rag.engine import GenerationUnavailableError
from project_service.server.grpc.generated import retrieval_service_pb2
from project_service.server.grpc.generated import retrieval_service_pb2_grpc
from retrieval_service.llm import OpenRouterClientError
from shared.queue import QueueFullError

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
        generation_engine: Any = None,
        health_checker: Any = None,
    ) -> None:
        self._manager = manager
        self._generation_engine = generation_engine
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
        except QueueFullError as exc:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, str(exc))
        except ManagerIngestTimeoutError as exc:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, str(exc))
        except ManagerIngestFailedError as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))
        except Exception:
            logger.exception("manager ingest failed")
            await context.abort(grpc.StatusCode.INTERNAL, "internal error")
        return retrieval_service_pb2.IngestResponse(
            job_id=str(getattr(result, "job_id", "")),
            status=str(getattr(result, "status", "")),
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
        return retrieval_service_pb2.GetIngestJobStatusResponse(
            job_id=str(getattr(result, "job_id", "")),
            status=str(getattr(result, "status", "")),
            error=getattr(result, "error", "") or "",
            doc_id=getattr(result, "doc_id", "") or "",
        )

    # -- Generate (temporary compat pass-through) -------------------------

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


# -- Helpers ---------------------------------------------------------------


class _Namespace(SimpleNamespace):
    """Lightweight request DTO passed to ManagerService methods.

    ManagerService reads fields via getattr, so a SimpleNamespace subclass
    suffices — no need to import project_service gateway request types.
    """


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
