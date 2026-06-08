"""Reusable gRPC client for save-then-retrieve test flows."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import grpc

from server.grpc.generated import retrieval_service_pb2
from server.grpc.generated import retrieval_service_pb2_grpc

DEFAULT_TARGET = "localhost:50051"


@dataclass(slots=True)
class SaveAndRetrieveResult:
    job_id: str
    ingest_response: retrieval_service_pb2.IngestResponse
    job_status: retrieval_service_pb2.GetIngestJobStatusResponse
    search_response: retrieval_service_pb2.SearchResponse
    post: dict[str, Any]
    query: str

    @property
    def retrieved_texts(self) -> list[str]:
        return [chunk.text for chunk in self.search_response.chunks]


@dataclass(frozen=True, slots=True)
class PostPayload:
    raw_text: str
    query: str | None = None
    doc_id: str | None = None
    source_uri: str | None = None
    kb_id: str | None = None
    content_type: str = "text/plain"
    metadata: Mapping[str, Any] = field(default_factory=dict)


class RagServiceTestClient:
    """Small async client for ingesting a post and retrieving it back."""

    def __init__(
        self,
        *,
        target: str = DEFAULT_TARGET,
        project_id: str = "demo",
        user_id: str = "user_1",
        default_kb_id: str = "default",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.target = target
        self.project_id = project_id
        self.user_id = user_id
        self.default_kb_id = default_kb_id
        self.timeout_seconds = timeout_seconds
        self._channel: grpc.aio.Channel | None = None
        self._stub: retrieval_service_pb2_grpc.RagServiceStub | None = None

    async def __aenter__(self) -> RagServiceTestClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._channel is not None:
            return
        self._channel = grpc.aio.insecure_channel(self.target)
        self._stub = retrieval_service_pb2_grpc.RagServiceStub(self._channel)
        await asyncio.wait_for(
            self._channel.channel_ready(),
            timeout=self.timeout_seconds,
        )

    async def close(self) -> None:
        if self._channel is None:
            return
        await self._channel.close()
        self._channel = None
        self._stub = None

    async def save_post(
        self,
        post: str | Mapping[str, Any] | PostPayload,
        *,
        doc_id: str | None = None,
        source_uri: str | None = None,
        kb_id: str | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> retrieval_service_pb2.IngestResponse:
        payload = self._normalize_post(
            post,
            doc_id=doc_id,
            source_uri=source_uri,
            kb_id=kb_id,
            content_type=content_type,
            metadata=metadata,
        )
        await self._ensure_connected()
        assert self._stub is not None
        request = retrieval_service_pb2.IngestRequest(
            project_id=self.project_id,
            user_id=self.user_id,
            kb_id=payload["kb_id"],
            doc_id=payload["doc_id"],
            source_uri=payload["source_uri"],
            content_type=payload["content_type"],
            metadata={k: str(v) for k, v in payload["metadata"].items()},
        )
        return await self._stub.Ingest(request, timeout=self.timeout_seconds)

    async def wait_for_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval: float = 0.25,
    ) -> retrieval_service_pb2.GetIngestJobStatusResponse:
        await self._ensure_connected()
        assert self._stub is not None
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        deadline = asyncio.get_running_loop().time() + timeout

        while True:
            response = await self._stub.GetIngestJobStatus(
                retrieval_service_pb2.GetIngestJobStatusRequest(job_id=job_id),
                timeout=timeout,
            )
            status = response.status.lower()
            if status not in {"pending", "running"}:
                return response
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"timed out waiting for ingest job {job_id}")
            await asyncio.sleep(poll_interval)

    async def retrieve(
        self,
        query: str,
        *,
        kb_ids: Sequence[str] | None = None,
        include_shared: bool = True,
    ) -> retrieval_service_pb2.SearchResponse:
        await self._ensure_connected()
        assert self._stub is not None
        request = retrieval_service_pb2.SearchRequest(
            project_id=self.project_id,
            user_id=self.user_id,
            query=query,
            kb_ids=list(kb_ids or ()),
            include_shared=include_shared,
        )
        return await self._stub.Search(request, timeout=self.timeout_seconds)

    async def save_and_retrieve(
        self,
        post: str | Mapping[str, Any] | PostPayload,
        *,
        query: str | None = None,
        doc_id: str | None = None,
        source_uri: str | None = None,
        kb_id: str | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        kb_ids: Sequence[str] | None = None,
        include_shared: bool = True,
    ) -> SaveAndRetrieveResult:
        payload = self._normalize_post(
            post,
            query=query,
            doc_id=doc_id,
            source_uri=source_uri,
            kb_id=kb_id,
            content_type=content_type,
            metadata=metadata,
        )
        ingest_response = await self.save_post(
            payload,
            doc_id=payload["doc_id"],
            source_uri=payload["source_uri"],
            kb_id=payload["kb_id"],
            content_type=payload["content_type"],
            metadata=payload["metadata"],
        )
        job_status = await self.wait_for_job(ingest_response.job_id)
        if job_status.status.lower() != "completed":
            raise RuntimeError(
                f"ingest job {ingest_response.job_id} ended as "
                f"{job_status.status}: {job_status.error}"
            )
        search_response = await self.retrieve(
            payload["query"],
            kb_ids=kb_ids if kb_ids is not None else (payload["kb_id"],),
            include_shared=include_shared,
        )
        return SaveAndRetrieveResult(
            job_id=ingest_response.job_id,
            ingest_response=ingest_response,
            job_status=job_status,
            search_response=search_response,
            post=payload,
            query=payload["query"],
        )

    async def _ensure_connected(self) -> None:
        if self._channel is None or self._stub is None:
            await self.connect()

    def _normalize_post(
        self,
        post: str | Mapping[str, Any] | PostPayload,
        *,
        query: str | None = None,
        doc_id: str | None = None,
        source_uri: str | None = None,
        kb_id: str | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(post, PostPayload):
            raw_text = post.raw_text
            post_map: dict[str, Any] = {
                "query": post.query,
                "doc_id": post.doc_id,
                "source_uri": post.source_uri,
                "kb_id": post.kb_id,
                "content_type": post.content_type,
                "metadata": dict(post.metadata),
            }
        elif isinstance(post, str):
            raw_text = post
            post_map = {}
        elif isinstance(post, Mapping):
            post_map = dict(post)
            raw_text_value = post_map.pop("raw_text", None)
            if raw_text_value is None:
                raw_text_value = post_map.pop("text", None)
            if raw_text_value is None:
                raw_text_value = post_map.pop("content", "")
            raw_text = str(raw_text_value)
        else:
            raise TypeError("post must be a string, mapping, or PostPayload")

        if not raw_text.strip():
            raise ValueError("post content is required")

        reserved = {
            "query",
            "doc_id",
            "source_uri",
            "kb_id",
            "content_type",
            "metadata",
            "raw_text",
            "text",
            "content",
        }
        merged_metadata: dict[str, Any] = {}
        if isinstance(metadata, Mapping):
            merged_metadata.update(metadata)
        if "metadata" in post_map and isinstance(post_map["metadata"], Mapping):
            merged_metadata.update(dict(post_map.pop("metadata")))
        for key in list(post_map):
            if key not in reserved:
                merged_metadata[key] = post_map.pop(key)

        resolved_doc_id = (
            doc_id
            or post_map.get("doc_id")
            or f"post_{uuid.uuid4().hex[:12]}"
        )
        resolved_source_uri = (
            source_uri
            or post_map.get("source_uri")
            or f"memory://{resolved_doc_id}"
        )
        resolved_kb_id = kb_id or post_map.get("kb_id") or self.default_kb_id
        resolved_content_type = (
            content_type or post_map.get("content_type") or "text/plain"
        )
        resolved_query = (
            query
            or post_map.get("query")
            or raw_text.splitlines()[0].strip()
            or raw_text
        )

        merged_metadata["raw_text"] = raw_text

        return {
            "raw_text": raw_text,
            "query": str(resolved_query),
            "doc_id": str(resolved_doc_id),
            "source_uri": str(resolved_source_uri),
            "kb_id": str(resolved_kb_id),
            "content_type": str(resolved_content_type),
            "metadata": merged_metadata,
        }


__all__ = [
    "DEFAULT_TARGET",
    "PostPayload",
    "RagServiceTestClient",
    "SaveAndRetrieveResult",
]
