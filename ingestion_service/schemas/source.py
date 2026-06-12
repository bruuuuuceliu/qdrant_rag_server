"""Source input schemas for ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """Project-neutral description of a source to ingest."""

    source_uri: str
    content_type: str = "text/plain"
    document_id: str = ""
    filename: str = ""
    data_type: str = "document"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_request(cls, request: Any) -> "SourceDescriptor":
        metadata = dict(getattr(request, "metadata", {}) or {})
        return cls(
            source_uri=str(getattr(request, "source_uri", "")),
            content_type=str(getattr(request, "content_type", "text/plain")),
            document_id=str(getattr(request, "doc_id", "")),
            filename=str(metadata.get("filename", "")),
            data_type=str(metadata.get("data_type", "document")),
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class SourceBlob:
    """Loaded source bytes plus normalized source metadata."""

    source_uri: str
    content: bytes
    content_type: str
    filename: str = ""
    document_id: str = ""
    data_type: str = "document"
    checksum: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_length(self) -> int:
        return len(self.content)

    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")
