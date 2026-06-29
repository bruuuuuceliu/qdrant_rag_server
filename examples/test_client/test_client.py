"""Reusable local/remote test client for the RAG service examples.

The main edge API exposed by ``examples/local/run-all.sh`` is gRPC. The
retrieval helper also exposes HTTP POST endpoints, so this client includes both
surfaces for manual local and remote smoke tests.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import os
import uuid
from typing import Any

import grpc
import httpx
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message

from project_service.server.grpc.generated import retrieval_service_pb2
from project_service.server.grpc.generated import retrieval_service_pb2_grpc


DEFAULT_GRPC_TARGET = "127.0.0.1:50051"
DEFAULT_HTTP_BASE_URL = "http://127.0.0.1:8081"
DEFAULT_PROJECT_ID = "demo"
DEFAULT_USER_ID = "user_1"
DEFAULT_KB_ID = "demo"
DEFAULT_DOC_ID = "test_client_doc"
DEFAULT_VERSION = "v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
INGEST_ACCEPTED_STATUSES = {"accepted", "pending", "running", "dispatched", "completed"}
TERMINAL_INGEST_STATUSES = {"completed", "failed"}


@dataclass(frozen=True, slots=True)
class RagTestClientConfig:
    """Configuration for local or remote RAG test-client calls."""

    grpc_target: str = DEFAULT_GRPC_TARGET
    grpc_secure: bool = False
    http_base_url: str = DEFAULT_HTTP_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    project_id: str = DEFAULT_PROJECT_ID
    user_id: str = DEFAULT_USER_ID
    kb_id: str = DEFAULT_KB_ID
    doc_id: str = DEFAULT_DOC_ID
    collection_name: str = ""
    include_shared: bool = True
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "RagTestClientConfig":
        values = os.environ if env is None else env
        project_id = values.get("RAG_TEST_PROJECT_ID", DEFAULT_PROJECT_ID)
        version = values.get("RAG_TEST_COLLECTION_VERSION", DEFAULT_VERSION)
        collection_name = values.get(
            "RAG_TEST_COLLECTION_NAME",
            f"rag_{project_id}_{version}",
        )
        return cls(
            grpc_target=values.get("RAG_TEST_GRPC_TARGET", DEFAULT_GRPC_TARGET),
            grpc_secure=_bool_env(values.get("RAG_TEST_GRPC_SECURE"), default=False),
            http_base_url=values.get("RAG_TEST_HTTP_BASE_URL", DEFAULT_HTTP_BASE_URL),
            timeout_seconds=float(
                values.get("RAG_TEST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
            ),
            project_id=project_id,
            user_id=values.get("RAG_TEST_USER_ID", DEFAULT_USER_ID),
            kb_id=values.get("RAG_TEST_KB_ID", DEFAULT_KB_ID),
            doc_id=values.get("RAG_TEST_DOC_ID", DEFAULT_DOC_ID),
            collection_name=collection_name,
            include_shared=_bool_env(
                values.get("RAG_TEST_INCLUDE_SHARED"),
                default=True,
            ),
            metadata=_json_env(values.get("RAG_TEST_METADATA")),
        )


class RagTestClient:
    """Small client wrapper used by the runnable examples in this package."""

    def __init__(
        self,
        config: RagTestClientConfig | None = None,
        *,
        grpc_stub: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or RagTestClientConfig.from_env()
        self._stub = grpc_stub
        self._channel: grpc.aio.Channel | None = None
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def __aenter__(self) -> "RagTestClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._stub is None:
            self._channel = _grpc_channel(self.config)
            self._stub = retrieval_service_pb2_grpc.RagServiceStub(self._channel)

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
        if self._http_client is not None and self._owns_http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def health(self) -> dict[str, Any]:
        response = await self._require_stub().HealthCheck(
            retrieval_service_pb2.HealthCheckRequest(),
            timeout=self.config.timeout_seconds,
        )
        return protobuf_to_dict(response)

    async def ingest(
        self,
        *,
        doc_id: str | None = None,
        text: str,
        source_uri: str | None = None,
        content_type: str = "text/plain",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request = self.build_ingest_request(
            doc_id=doc_id,
            text=text,
            source_uri=source_uri,
            content_type=content_type,
            metadata=metadata,
        )
        response = await self._require_stub().Ingest(
            request,
            timeout=self.config.timeout_seconds,
        )
        payload = protobuf_to_dict(response)
        require_ingest_response(payload)
        return payload

    async def ingest_status(self, job_id: str) -> dict[str, Any]:
        response = await self._require_stub().GetIngestJobStatus(
            retrieval_service_pb2.GetIngestJobStatusRequest(job_id=job_id),
            timeout=self.config.timeout_seconds,
        )
        payload = protobuf_to_dict(response)
        require_ingest_status_response(payload, expected_job_id=job_id)
        return payload

    async def wait_for_ingest_status(
        self,
        job_id: str,
        *,
        poll_seconds: float = 1.0,
        max_attempts: int = 30,
    ) -> dict[str, Any]:
        last_status: dict[str, Any] = {}
        for _ in range(max_attempts):
            last_status = await self.ingest_status(job_id)
            status = str(last_status.get("status", "")).lower()
            if status in TERMINAL_INGEST_STATUSES:
                return last_status
            await asyncio.sleep(poll_seconds)
        raise RuntimeError(
            f"ingest job {job_id} did not reach a terminal status after "
            f"{max_attempts} attempts; last status: {last_status}"
        )

    async def search(
        self,
        *,
        query: str,
        kb_ids: tuple[str, ...] | list[str] | None = None,
        include_shared: bool | None = None,
    ) -> dict[str, Any]:
        request = self.build_search_request(
            query=query,
            kb_ids=kb_ids,
            include_shared=include_shared,
        )
        response = await self._require_stub().Search(
            request,
            timeout=self.config.timeout_seconds,
        )
        payload = protobuf_to_dict(response)
        require_search_response(payload)
        return payload

    async def generate(
        self,
        *,
        query: str,
        chunks: list[dict[str, Any]],
        openrouter_api_key: str,
        model: str = "",
    ) -> dict[str, Any]:
        request = retrieval_service_pb2.GenerateRequest(
            project_id=self.config.project_id,
            user_id=self.config.user_id,
            query=query,
            chunks=[_chunk_from_mapping(chunk) for chunk in chunks],
            openrouter_api_key=openrouter_api_key,
            model=model,
        )
        response = await self._require_stub().Generate(
            request,
            timeout=self.config.timeout_seconds,
        )
        return protobuf_to_dict(response)

    async def http_health(self) -> dict[str, Any]:
        response = await self._require_http_client().get(self._url("/health"))
        return _json_response(response)

    async def post_search(
        self,
        *,
        query: str,
        request_id: str | None = None,
        retrieval_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            "/search",
            self.build_http_search_payload(
                query=query,
                request_id=request_id,
                retrieval_config=retrieval_config,
            ),
        )

    async def post_delete_document(
        self,
        *,
        doc_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            "/documents/delete",
            self.build_http_delete_payload(doc_id=doc_id, request_id=request_id),
        )

    async def post_raw_document(
        self,
        *,
        doc_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            "/documents/raw",
            self.build_http_raw_document_payload(doc_id=doc_id, request_id=request_id),
        )

    def build_ingest_request(
        self,
        *,
        doc_id: str | None = None,
        text: str,
        source_uri: str | None = None,
        content_type: str = "text/plain",
        metadata: dict[str, str] | None = None,
    ) -> retrieval_service_pb2.IngestRequest:
        resolved_doc_id = doc_id or self.config.doc_id
        request_metadata = dict(self.config.metadata)
        if metadata:
            request_metadata.update({str(key): str(value) for key, value in metadata.items()})
        request_metadata["raw_text"] = text
        return retrieval_service_pb2.IngestRequest(
            project_id=self.config.project_id,
            user_id=self.config.user_id,
            kb_id=self.config.kb_id,
            doc_id=resolved_doc_id,
            source_uri=source_uri or f"memory://{resolved_doc_id}",
            content_type=content_type,
            metadata=request_metadata,
        )

    def build_search_request(
        self,
        *,
        query: str,
        kb_ids: tuple[str, ...] | list[str] | None = None,
        include_shared: bool | None = None,
    ) -> retrieval_service_pb2.SearchRequest:
        return retrieval_service_pb2.SearchRequest(
            project_id=self.config.project_id,
            user_id=self.config.user_id,
            query=query,
            kb_ids=list(kb_ids if kb_ids is not None else (self.config.kb_id,)),
            include_shared=(
                self.config.include_shared
                if include_shared is None
                else bool(include_shared)
            ),
        )

    def build_http_search_payload(
        self,
        *,
        query: str,
        request_id: str | None = None,
        retrieval_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "request_id": request_id or _request_id("search"),
            "request": {
                "project_id": self.config.project_id,
                "user_id": self.config.user_id,
                "query_text": query,
                "collection_name": self.config.collection_name,
                "retrieval_config": dict(retrieval_config or {"top_k": 5}),
                "retrieval_filter": self._retrieval_filter(),
            },
        }

    def build_http_delete_payload(
        self,
        *,
        doc_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "request_id": request_id or _request_id("delete"),
            "request": {
                "project_id": self.config.project_id,
                "user_id": self.config.user_id,
                "kb_id": self.config.kb_id,
                "doc_id": doc_id or self.config.doc_id,
                "collection_name": self.config.collection_name,
            },
        }

    def build_http_raw_document_payload(
        self,
        *,
        doc_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "request_id": request_id or _request_id("raw"),
            "request": {
                "project_id": self.config.project_id,
                "user_id": self.config.user_id,
                "doc_id": doc_id or self.config.doc_id,
            },
        }

    def _retrieval_filter(self) -> dict[str, Any]:
        allowed_user_ids = [self.config.user_id]
        if self.config.include_shared:
            allowed_user_ids.append("__shared__")
        return {
            "project_id": self.config.project_id,
            "allowed_user_ids": allowed_user_ids,
            "kb_ids": [self.config.kb_id],
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._require_http_client().post(self._url(path), json=payload)
        return _json_response(response)

    def _url(self, path: str) -> str:
        return f"{self.config.http_base_url.rstrip('/')}/{path.lstrip('/')}"

    def _require_stub(self) -> Any:
        if self._stub is None:
            raise RuntimeError("RagTestClient.connect() must be called before gRPC use")
        return self._stub

    def _require_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                trust_env=False,
            )
        return self._http_client


def protobuf_to_dict(message: Message) -> dict[str, Any]:
    return MessageToDict(
        message,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def require_health_response(payload: dict[str, Any]) -> None:
    status = str(payload.get("status", "")).lower()
    if status not in {"healthy", "ok"}:
        raise RuntimeError(f"health check did not report healthy status: {payload}")


def require_ingest_response(payload: dict[str, Any]) -> None:
    job_id = str(payload.get("job_id", "")).strip()
    status = str(payload.get("status", "")).lower()
    if not job_id:
        raise RuntimeError(f"ingest response did not include a job_id: {payload}")
    if status not in INGEST_ACCEPTED_STATUSES and status not in TERMINAL_INGEST_STATUSES:
        raise RuntimeError(f"ingest response had unexpected status: {payload}")


def require_ingest_status_response(
    payload: dict[str, Any],
    *,
    expected_job_id: str | None = None,
) -> None:
    job_id = str(payload.get("job_id", "")).strip()
    status = str(payload.get("status", "")).lower()
    if not job_id:
        raise RuntimeError(f"ingest status response did not include a job_id: {payload}")
    if expected_job_id is not None and job_id != expected_job_id:
        raise RuntimeError(
            f"ingest status job_id mismatch: expected {expected_job_id}, got {job_id}"
        )
    if status not in INGEST_ACCEPTED_STATUSES and status not in TERMINAL_INGEST_STATUSES:
        raise RuntimeError(f"ingest status response had unexpected status: {payload}")


def require_terminal_ingest_status(payload: dict[str, Any]) -> None:
    status = str(payload.get("status", "")).lower()
    if status != "completed":
        raise RuntimeError(f"ingest did not complete successfully: {payload}")


def require_search_response(payload: dict[str, Any], *, require_chunks: bool = False) -> None:
    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        raise RuntimeError(f"search response did not include chunks: {payload}")
    if require_chunks and not chunks:
        raise RuntimeError(f"search response did not include any chunks: {payload}")


def require_http_envelope(
    payload: dict[str, Any],
    *,
    require_result: bool = True,
) -> None:
    if payload.get("ok") is not True:
        raise RuntimeError(f"HTTP API returned an error envelope: {payload}")
    if require_result and not isinstance(payload.get("result"), dict):
        raise RuntimeError(f"HTTP API response did not include a result object: {payload}")


def parse_common_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    add_common_args(parser)
    return parser.parse_args()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--grpc-target", default=None)
    parser.add_argument("--grpc-secure", action="store_true")
    parser.add_argument("--http-base-url", default=None)
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--kb-id", default=None)
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--collection-name", default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--no-shared", action="store_true")


def config_from_args(args: argparse.Namespace) -> RagTestClientConfig:
    config = RagTestClientConfig.from_env()
    project_id = args.project_id or config.project_id
    collection_name = (
        args.collection_name
        or os.environ.get("RAG_TEST_COLLECTION_NAME")
        or (
            f"rag_{project_id}_"
            f"{os.environ.get('RAG_TEST_COLLECTION_VERSION', DEFAULT_VERSION)}"
        )
    )
    return RagTestClientConfig(
        grpc_target=args.grpc_target or config.grpc_target,
        grpc_secure=config.grpc_secure or bool(args.grpc_secure),
        http_base_url=args.http_base_url or config.http_base_url,
        timeout_seconds=args.timeout or config.timeout_seconds,
        project_id=project_id,
        user_id=args.user_id or config.user_id,
        kb_id=args.kb_id or config.kb_id,
        doc_id=args.doc_id or config.doc_id,
        collection_name=collection_name,
        include_shared=False if args.no_shared else config.include_shared,
        metadata=dict(config.metadata),
    )


def _grpc_channel(config: RagTestClientConfig) -> grpc.aio.Channel:
    if config.grpc_secure:
        return grpc.aio.secure_channel(config.grpc_target, grpc.ssl_channel_credentials())
    return grpc.aio.insecure_channel(config.grpc_target)


def _chunk_from_mapping(chunk: dict[str, Any]) -> retrieval_service_pb2.ChunkResult:
    return retrieval_service_pb2.ChunkResult(
        project_id=str(chunk.get("project_id", "")),
        user_id=str(chunk.get("user_id", "")),
        kb_id=str(chunk.get("kb_id", "")),
        doc_id=str(chunk.get("doc_id", "")),
        chunk_id=str(chunk.get("chunk_id", "")),
        chunk_index=int(chunk.get("chunk_index", 0)),
        text=str(chunk.get("text", "")),
        score=float(chunk.get("score", 0.0)),
        metadata={str(k): str(v) for k, v in dict(chunk.get("metadata", {})).items()},
    )


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"HTTP request to {response.request.url} failed with "
            f"{response.status_code}: {response.text}"
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"response from {response.request.url} was not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"response from {response.request.url} must be a JSON object")
    return dict(payload)


def _bool_env(value: str | None, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _json_env(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("RAG_TEST_METADATA must be a JSON object")
    return {str(key): str(item) for key, item in loaded.items()}


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"
