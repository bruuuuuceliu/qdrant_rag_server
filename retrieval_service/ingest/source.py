"""Source loading helpers for ingest implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


@dataclass(frozen=True, slots=True)
class IngestSourceContent:
    source_uri: str
    text: str
    raw_content: bytes
    content_type: str


async def load_ingest_source(request: Any) -> IngestSourceContent:
    """Load text from request metadata, a local path, file URL, or HTTP URL."""

    metadata = dict(getattr(request, "metadata", {}) or {})
    content_type = str(getattr(request, "content_type", "text/plain"))
    source_uri = str(getattr(request, "source_uri", ""))

    raw_text = metadata.get("raw_text")
    if raw_text is not None:
        text = str(raw_text)
        return IngestSourceContent(
            source_uri=source_uri,
            text=text,
            raw_content=text.encode("utf-8"),
            content_type=content_type,
        )

    parsed = urlparse(source_uri)
    if parsed.scheme in {"http", "https"}:
        return await _load_http_source(source_uri, fallback_content_type=content_type)

    path = _source_path(source_uri, parsed)
    if path is not None and path.exists() and path.is_file():
        raw_content = path.read_bytes()
        text = raw_content.decode("utf-8", errors="replace")
        return IngestSourceContent(
            source_uri=source_uri,
            text=text,
            raw_content=raw_content,
            content_type=content_type,
        )

    text = source_uri
    return IngestSourceContent(
        source_uri=source_uri,
        text=text,
        raw_content=text.encode("utf-8"),
        content_type=content_type,
    )


async def _load_http_source(
    source_uri: str,
    *,
    fallback_content_type: str,
) -> IngestSourceContent:
    import httpx

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(source_uri)
        response.raise_for_status()
    content_type = response.headers.get("content-type", fallback_content_type)
    return IngestSourceContent(
        source_uri=source_uri,
        text=response.text,
        raw_content=response.content,
        content_type=content_type,
    )


def _source_path(source_uri: str, parsed: Any) -> Path | None:
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if parsed.scheme:
        return None
    return Path(source_uri).expanduser()
