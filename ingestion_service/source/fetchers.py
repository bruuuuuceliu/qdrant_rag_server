"""Source loading helpers for standalone ingestion."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ingestion_service.errors import SourceLoadError, SourceTooLargeError
from ingestion_service.schemas import DocumentHandlingPolicy, SourceBlob, SourceDescriptor
from ingestion_service.source.detectors import detect_content_type


async def load_source(
    source: SourceDescriptor | Any,
    *,
    policy: DocumentHandlingPolicy | None = None,
) -> SourceBlob:
    """Load source content from raw metadata, local paths, file URLs, or HTTP URLs."""

    policy = policy or DocumentHandlingPolicy()
    descriptor = (
        source if isinstance(source, SourceDescriptor) else SourceDescriptor.from_request(source)
    )
    metadata = dict(descriptor.metadata)

    raw_content = metadata.get("raw_content")
    raw_text = metadata.get("raw_text")
    if raw_content is not None:
        content = _coerce_bytes(raw_content)
        return _make_blob(descriptor, content=content, policy=policy)
    if raw_text is not None:
        content = str(raw_text).encode("utf-8")
        return _make_blob(descriptor, content=content, policy=policy)

    parsed = urlparse(descriptor.source_uri)
    _validate_scheme(parsed.scheme, policy)
    if parsed.scheme in {"http", "https"}:
        return await _load_http_source(descriptor, policy=policy)

    path = _source_path(descriptor.source_uri, parsed)
    if path is not None and path.exists() and path.is_file():
        if parsed.scheme in {"", "file"} and not policy.allow_local_files:
            raise SourceLoadError("local file ingestion is disabled by policy")
        content = path.read_bytes()
        return _make_blob(descriptor, content=content, policy=policy)

    content = descriptor.source_uri.encode("utf-8")
    return _make_blob(descriptor, content=content, policy=policy)


async def _load_http_source(
    descriptor: SourceDescriptor,
    *,
    policy: DocumentHandlingPolicy,
) -> SourceBlob:
    import httpx

    async with httpx.AsyncClient(
        timeout=policy.budget.timeout_seconds,
        follow_redirects=True,
    ) as client:
        response = await client.get(descriptor.source_uri)
        response.raise_for_status()
    content = response.content
    content_type = response.headers.get("content-type", descriptor.content_type)
    updated = SourceDescriptor(
        source_uri=str(response.url),
        content_type=content_type,
        document_id=descriptor.document_id,
        filename=descriptor.filename,
        data_type=descriptor.data_type,
        metadata=dict(descriptor.metadata),
    )
    return _make_blob(updated, content=content, policy=policy)


def _make_blob(
    descriptor: SourceDescriptor,
    *,
    content: bytes,
    policy: DocumentHandlingPolicy,
) -> SourceBlob:
    if len(content) > policy.budget.max_source_bytes:
        raise SourceTooLargeError(
            f"source is {len(content)} bytes; limit is {policy.budget.max_source_bytes}"
        )
    content_type = detect_content_type(
        declared_content_type=descriptor.content_type,
        source_uri=descriptor.source_uri,
        filename=descriptor.filename,
        content=content,
    )
    return SourceBlob(
        source_uri=descriptor.source_uri,
        content=content,
        content_type=content_type,
        filename=descriptor.filename,
        document_id=descriptor.document_id,
        data_type=descriptor.data_type,
        checksum=hashlib.sha256(content).hexdigest(),
        metadata=dict(descriptor.metadata),
    )


def _validate_scheme(scheme: str, policy: DocumentHandlingPolicy) -> None:
    if scheme not in policy.allowed_schemes:
        raise SourceLoadError(f"source scheme {scheme!r} is not allowed")


def _source_path(source_uri: str, parsed: Any) -> Path | None:
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if parsed.scheme:
        return None
    return Path(source_uri).expanduser()


def _coerce_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    return str(value).encode("utf-8")
