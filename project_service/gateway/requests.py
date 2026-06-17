"""Gateway request schemas — validated input DTOs from transport layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from project_service.gateway.helpers import (
    DEFAULT_KB_ID,
    _normalize_optional_str,
    _reject_raw_filters,
    _required_str,
    _validate_non_empty,
)


@dataclass(frozen=True, slots=True)
class SearchRequest:
    project_id: str
    user_id: str
    query: str
    kb_ids: tuple[str, ...] = ()
    include_shared: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> SearchRequest:
        _reject_raw_filters(data)
        return cls(
            project_id=_required_str(data, "project_id"),
            user_id=_required_str(data, "user_id"),
            query=_required_str(data, "query"),
            kb_ids=tuple(data.get("kb_ids", ())),
            include_shared=bool(data.get("include_shared", True)),
        )

    def __post_init__(self) -> None:
        _validate_non_empty("project_id", self.project_id)
        _validate_non_empty("user_id", self.user_id)
        _validate_non_empty("query", self.query)
        object.__setattr__(self, "kb_ids", tuple(self.kb_ids))


@dataclass(frozen=True, slots=True)
class IngestRequest:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    source_uri: str
    content_type: str
    raw_text: str | None = None
    raw_content: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> IngestRequest:
        return cls(
            project_id=_required_str(data, "project_id"),
            user_id=_required_str(data, "user_id"),
            kb_id=_optional_str(data, "kb_id", DEFAULT_KB_ID),
            doc_id=_required_str(data, "doc_id"),
            source_uri=_required_str(data, "source_uri"),
            content_type=_required_str(data, "content_type"),
            raw_text=_optional_raw_text(data.get("raw_text")),
            raw_content=_optional_raw_content(data.get("raw_content")),
            metadata=dict(data.get("metadata", {})),
        )

    def __post_init__(self) -> None:
        _validate_non_empty("project_id", self.project_id)
        _validate_non_empty("user_id", self.user_id)
        object.__setattr__(
            self,
            "kb_id",
            _normalize_optional_str(self.kb_id, DEFAULT_KB_ID, field_name="kb_id"),
        )
        _validate_non_empty("doc_id", self.doc_id)
        _validate_non_empty("source_uri", self.source_uri)
        _validate_non_empty("content_type", self.content_type)
        if self.raw_text is not None and self.raw_content is not None:
            raise ValueError("raw_text and raw_content are mutually exclusive")
        if self.raw_content is not None:
            object.__setattr__(self, "raw_content", bytes(self.raw_content))


@dataclass(frozen=True, slots=True)
class DeleteDocumentRequest:
    project_id: str
    user_id: str
    kb_id: str
    doc_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> DeleteDocumentRequest:
        return cls(
            project_id=_required_str(data, "project_id"),
            user_id=_required_str(data, "user_id"),
            kb_id=_optional_str(data, "kb_id", DEFAULT_KB_ID),
            doc_id=_required_str(data, "doc_id"),
            metadata=dict(data.get("metadata", {})),
        )

    def __post_init__(self) -> None:
        _validate_non_empty("project_id", self.project_id)
        _validate_non_empty("user_id", self.user_id)
        object.__setattr__(
            self,
            "kb_id",
            _normalize_optional_str(self.kb_id, DEFAULT_KB_ID, field_name="kb_id"),
        )
        _validate_non_empty("doc_id", self.doc_id)


def _optional_str(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    return _normalize_optional_str(value, default, field_name=key)


def _optional_raw_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_raw_content(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    return str(value).encode("utf-8")
