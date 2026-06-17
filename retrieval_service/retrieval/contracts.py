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
        )

    def request_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "query_text": self.query_text,
            "collection_name": self.collection_name,
            "retrieval_config": dict(self.retrieval_config),
            "cache_key": self.cache_key,
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
        )

    def request_payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "kb_id": self.kb_id,
            "doc_id": self.doc_id,
            "collection_name": self.collection_name,
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
