"""Normalized document and chunk schemas produced by ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class IngestedSection:
    section_id: str
    text: str
    heading: str = ""
    order: int = 0
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    document_id: str
    source_uri: str
    content_type: str = "text/plain"
    data_type: str = "document"
    content_hash: str = ""
    title: str = ""
    handler_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngestedChunk:
    document_id: str
    chunk_id: str
    chunk_index: int
    text: str
    data_type: str = "document"
    content_hash: str = ""
    chunker_version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HandlerOutput:
    document: IngestedDocument
    sections: tuple[IngestedSection, ...]
