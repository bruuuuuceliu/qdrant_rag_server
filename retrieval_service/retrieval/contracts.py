"""Transport-neutral retrieval API contract types."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from retrieval_service.retrieval.service import (
    DeleteDocumentRequest,
    RawDocumentRequest,
    RetrievalSearchRequest,
    RetrievalSearchResult,
)


@dataclass(frozen=True, slots=True)
class RetrievalApiError:
    """Structured retrieval API error carried in response envelopes."""

    code: str
    message: str
    retryable: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class RetrievalResponseEnvelope:
    """Typed response envelope for retrieval service boundary calls."""

    request_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: RetrievalApiError | None = None

    @classmethod
    def success(
        cls,
        *,
        request_id: str,
        result: dict[str, Any] | None = None,
    ) -> "RetrievalResponseEnvelope":
        return cls(request_id=request_id, ok=True, result=dict(result or {}))

    @classmethod
    def failure(
        cls,
        *,
        request_id: str,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> "RetrievalResponseEnvelope":
        return cls(
            request_id=request_id,
            ok=False,
            error=RetrievalApiError(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_id": self.request_id,
            "ok": self.ok,
        }
        if self.result is not None:
            payload["result"] = dict(self.result)
        if self.error is not None:
            payload["error"] = self.error.to_mapping()
        return payload


@dataclass(frozen=True, slots=True)
class RetrievalFilterSpec:
    """Retrieval-owned filter shape accepted through transport payloads."""

    project_id: str
    allowed_user_ids: tuple[str, ...]
    kb_ids: tuple[str, ...] = ()
    doc_ids: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "RetrievalFilterSpec":
        project_id = str(payload.get("project_id", ""))
        allowed_user_ids = _str_tuple(payload.get("allowed_user_ids"))
        if not allowed_user_ids and payload.get("user_id") is not None:
            allowed_user_ids = (str(payload.get("user_id")),)
        spec = cls(
            project_id=project_id,
            allowed_user_ids=allowed_user_ids,
            kb_ids=_str_tuple(payload.get("kb_ids")),
            doc_ids=_str_tuple(payload.get("doc_ids")),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        _require_fields(
            {
                "retrieval_filter.project_id": self.project_id,
                "retrieval_filter.allowed_user_ids": self.allowed_user_ids,
            }
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "allowed_user_ids": list(self.allowed_user_ids),
            "kb_ids": list(self.kb_ids),
            "doc_ids": list(self.doc_ids),
        }


@dataclass(frozen=True, slots=True)
class RetrievalSearchCommand:
    """Serializable search command accepted at the retrieval service boundary."""

    request_id: str
    project_id: str
    user_id: str
    query_text: str
    collection_name: str
    response_topic: str = ""
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    retrieval_filter: Any = None
    cache_key: str = ""
    placement_plan: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> "RetrievalSearchCommand":
        request_payload = _request_payload(payload)
        query_text = request_payload.get("query_text", request_payload.get("query", ""))
        return cls(
            request_id=str(payload.get("request_id") or fallback_request_id),
            response_topic=str(payload.get("response_topic") or ""),
            project_id=str(request_payload.get("project_id", "")),
            user_id=str(request_payload.get("user_id", "")),
            query_text=str(query_text),
            collection_name=str(request_payload.get("collection_name", "")),
            retrieval_config=_mapping(request_payload.get("retrieval_config")),
            retrieval_filter=_retrieval_filter(request_payload.get("retrieval_filter")),
            cache_key=str(request_payload.get("cache_key", "")),
            placement_plan=_mapping(request_payload.get("placement_plan")),
        )

    def request_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "query_text": self.query_text,
            "collection_name": self.collection_name,
            "retrieval_config": dict(self.retrieval_config),
            "cache_key": self.cache_key,
            "placement_plan": dict(self.placement_plan),
        }
        if self.retrieval_filter is not None:
            payload["retrieval_filter"] = _filter_payload(self.retrieval_filter)
        return payload

    def validate(self) -> None:
        _require_fields(
            {
                "request_id": self.request_id,
                "project_id": self.project_id,
                "user_id": self.user_id,
                "query_text": self.query_text,
                "collection_name": self.collection_name,
                "retrieval_filter": self.retrieval_filter,
            }
        )

    def to_service_request(self) -> RetrievalSearchRequest:
        self.validate()
        return RetrievalSearchRequest(
            project_id=self.project_id,
            user_id=self.user_id,
            query_text=self.query_text,
            collection_name=self.collection_name,
            retrieval_config=dict(self.retrieval_config),
            retrieval_filter=self.retrieval_filter,
            cache_key=self.cache_key,
            placement_plan=dict(self.placement_plan),
        )


@dataclass(frozen=True, slots=True)
class RetrievalDeleteDocumentCommand:
    """Serializable delete command accepted at the retrieval service boundary."""

    request_id: str
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    collection_name: str
    response_topic: str = ""
    placement_plan: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> "RetrievalDeleteDocumentCommand":
        request_payload = _request_payload(payload)
        return cls(
            request_id=str(payload.get("request_id") or fallback_request_id),
            response_topic=str(payload.get("response_topic") or ""),
            project_id=str(request_payload.get("project_id", "")),
            user_id=str(request_payload.get("user_id", "")),
            kb_id=str(request_payload.get("kb_id", "")),
            doc_id=str(request_payload.get("doc_id", "")),
            collection_name=str(request_payload.get("collection_name", "")),
            placement_plan=_mapping(request_payload.get("placement_plan")),
        )

    def request_payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "kb_id": self.kb_id,
            "doc_id": self.doc_id,
            "collection_name": self.collection_name,
            "placement_plan": dict(self.placement_plan),
        }

    def validate(self) -> None:
        _require_fields(
            {
                "request_id": self.request_id,
                "project_id": self.project_id,
                "user_id": self.user_id,
                "kb_id": self.kb_id,
                "doc_id": self.doc_id,
                "collection_name": self.collection_name,
            }
        )

    def to_service_request(self) -> DeleteDocumentRequest:
        self.validate()
        return DeleteDocumentRequest(
            project_id=self.project_id,
            user_id=self.user_id,
            kb_id=self.kb_id,
            doc_id=self.doc_id,
            collection_name=self.collection_name,
            placement_plan=dict(self.placement_plan),
        )


@dataclass(frozen=True, slots=True)
class RetrievalRawDocumentCommand:
    """Serializable raw-document command accepted at the retrieval boundary."""

    request_id: str
    project_id: str
    user_id: str
    doc_id: str
    response_topic: str = ""

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> "RetrievalRawDocumentCommand":
        request_payload = _request_payload(payload)
        return cls(
            request_id=str(payload.get("request_id") or fallback_request_id),
            response_topic=str(payload.get("response_topic") or ""),
            project_id=str(request_payload.get("project_id", "")),
            user_id=str(request_payload.get("user_id", "")),
            doc_id=str(request_payload.get("doc_id", "")),
        )

    def request_payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "doc_id": self.doc_id,
        }

    def validate(self) -> None:
        _require_fields(
            {
                "request_id": self.request_id,
                "project_id": self.project_id,
                "user_id": self.user_id,
                "doc_id": self.doc_id,
            }
        )

    def to_service_request(self) -> RawDocumentRequest:
        self.validate()
        return RawDocumentRequest(
            project_id=self.project_id,
            user_id=self.user_id,
            doc_id=self.doc_id,
        )


@dataclass(frozen=True, slots=True)
class MemorySearchCommand:
    """Serializable memory-search command accepted at the retrieval boundary.

    Targets the memory collection with an isolation filter over ``owner_id`` /
    ``agent_id`` (the keys the memory payloads carry), distinct from the
    document ``RetrievalSearchCommand`` which requires ``project_id`` /
    ``allowed_user_ids``.
    """

    request_id: str
    project_id: str
    user_id: str
    agent_id: str
    query_text: str
    collection_name: str
    response_topic: str = ""
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    cache_key: str = ""
    placement_plan: dict[str, Any] = field(default_factory=dict)
    owner_id: str = ""
    session_ids: tuple[str, ...] = ()
    top_k: int = 0

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fallback_request_id: str,
    ) -> "MemorySearchCommand":
        request_payload = _request_payload(payload)
        return cls(
            request_id=str(payload.get("request_id") or fallback_request_id),
            response_topic=str(payload.get("response_topic") or ""),
            project_id=str(request_payload.get("project_id", "")),
            user_id=str(request_payload.get("user_id", "")),
            agent_id=str(request_payload.get("agent_id", "")),
            query_text=str(
                request_payload.get("query_text", request_payload.get("query", ""))
            ),
            collection_name=str(request_payload.get("collection_name", "")),
            retrieval_config=_mapping(request_payload.get("retrieval_config")),
            cache_key=str(request_payload.get("cache_key", "")),
            placement_plan=_mapping(request_payload.get("placement_plan")),
            owner_id=str(request_payload.get("owner_id", "")),
            session_ids=_str_tuple(request_payload.get("session_ids")),
            top_k=_int_value(request_payload.get("top_k"), default=0),
        )

    def validate(self) -> None:
        _require_fields(
            {
                "request_id": self.request_id,
                "query_text": self.query_text,
                "collection_name": self.collection_name,
            }
        )

    def to_service_request(self) -> RetrievalSearchRequest:
        self.validate()
        return RetrievalSearchRequest(
            project_id=self.project_id or self.owner_id or "memory",
            user_id=self.user_id or self.owner_id or "memory",
            query_text=self.query_text,
            collection_name=self.collection_name,
            retrieval_config=dict(self.retrieval_config),
            retrieval_filter=None,
            cache_key=self.cache_key,
            placement_plan=dict(self.placement_plan),
            session_ids=self.session_ids,
            top_k=self.top_k,
        )


def memory_search_result_to_mapping(
    result: RetrievalSearchResult,
    *,
    agent_id: str = "",
    owner_id: str = "",
) -> dict[str, Any]:
    """Serialize a memory-search result as ``{source_id, text, score, ...}`` hits.

    The memory payload carries the source identity in ``memory_id`` (or
    ``document_id``) plus optional ``session_id``/``sequence_number`` in
    ``metadata``.
    """
    hits: list[dict[str, Any]] = []
    for chunk in result.chunks:
        payload = chunk if isinstance(chunk, dict) else {}
        source_id = (
            payload.get("memory_id")
            or payload.get("document_id")
            or payload.get("chunk_id")
            or ""
        )
        hit: dict[str, Any] = {
            "source_id": str(source_id),
            "text": str(payload.get("text", "")),
            "score": float(payload.get("score", 0.0)),
        }
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if payload.get("session_id"):
            hit["session_id"] = str(payload["session_id"])
        elif metadata.get("session_id"):
            hit["session_id"] = str(metadata["session_id"])
        if payload.get("sequence_number") is not None:
            hit["sequence_number"] = payload["sequence_number"]
        elif metadata.get("sequence_number") is not None:
            hit["sequence_number"] = metadata["sequence_number"]
        hit["memory_id"] = str(source_id)
        hit["agent_id"] = agent_id
        hit["owner_id"] = owner_id
        hits.append(hit)
    return {"hits": hits}


def search_result_to_mapping(result: RetrievalSearchResult) -> dict[str, Any]:
    """Serialize a retrieval search result for transport responses."""

    return {
        "chunks": [dict(chunk) for chunk in result.chunks],
        "elapsed_ms": result.elapsed_ms,
        "cache_hit": result.cache_hit,
    }


def raw_document_result_to_mapping(content: bytes | None) -> dict[str, Any]:
    """Serialize raw-document lookup metadata without assuming a wire format."""

    if content is None:
        return {
            "found": False,
            "content_b64": "",
            "encoding": "base64",
        }
    return {
        "found": True,
        "content_b64": base64.b64encode(content).decode("ascii"),
        "encoding": "base64",
    }


def _request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    if isinstance(request, dict):
        return dict(request)
    return dict(payload)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _retrieval_filter(value: Any) -> Any:
    if isinstance(value, dict):
        return RetrievalFilterSpec.from_mapping(value)
    return value


def _filter_payload(value: Any) -> Any:
    if isinstance(value, RetrievalFilterSpec):
        return value.to_mapping()
    return value


def _str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    try:
        return tuple(str(item) for item in value if str(item))
    except TypeError:
        return (str(value),) if str(value) else ()


def _int_value(value: Any, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _require_fields(fields: dict[str, Any]) -> None:
    missing = [name for name, value in fields.items() if _is_missing(value)]
    if missing:
        raise ValueError("missing required retrieval fields: " + ", ".join(missing))


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, tuple | list | set | dict):
        return len(value) == 0
    return False
