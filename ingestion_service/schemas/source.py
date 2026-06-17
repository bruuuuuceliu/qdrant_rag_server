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
        if isinstance(request, dict):
            metadata = dict(request.get("metadata", {}) or {})
            raw_text = request.get("raw_text")
            raw_content = request.get("raw_content")
            return cls(
                source_uri=str(request.get("source_uri", "")),
                content_type=str(request.get("content_type", "text/plain")),
                document_id=str(request.get("doc_id", "")),
                filename=str(metadata.get("filename", "")),
                data_type=str(metadata.get("data_type", "document")),
                metadata=_source_metadata(metadata, raw_text, raw_content),
            )
        metadata = dict(getattr(request, "metadata", {}) or {})
        raw_text = getattr(request, "raw_text", None)
        raw_content = getattr(request, "raw_content", None)
        metadata = _source_metadata(metadata, raw_text, raw_content)
        return cls(
            source_uri=str(getattr(request, "source_uri", "")),
            content_type=str(getattr(request, "content_type", "text/plain")),
            document_id=str(getattr(request, "doc_id", "")),
            filename=str(metadata.get("filename", "")),
            data_type=str(metadata.get("data_type", "document")),
            metadata=metadata,
        )


def _source_metadata(
    metadata: dict[str, Any],
    raw_text: Any,
    raw_content: Any,
) -> dict[str, Any]:
    metadata = dict(metadata)
    if raw_text is not None:
        metadata["raw_text"] = raw_text
    if raw_content is not None:
        metadata["raw_content"] = raw_content
    return metadata


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
