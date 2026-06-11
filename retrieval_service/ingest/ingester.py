"""Ingester contracts and prepared ingest data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PreparedIngestData:
    """Document payloads prepared for vector-store upload."""

    document: Any
    chunks: tuple[Any, ...]
    payloads: tuple[Any, ...]
    raw_content: bytes | None = None

    @property
    def texts(self) -> list[str]:
        return [str(getattr(chunk, "text", "")) for chunk in self.chunks]


class Ingester(Protocol):
    """Turns a file, URL, or ingest request into upload-ready payload data."""

    async def prepare(
        self,
        request: Any,
        *,
        config: Any | None = None,
    ) -> PreparedIngestData:
        ...


class AdapterBackedIngester:
    """Compatibility ingester for legacy adapters with ingest methods."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    async def prepare(
        self,
        request: Any,
        *,
        config: Any | None = None,
    ) -> PreparedIngestData:
        del config
        document = await self._adapter.parse_document(request)
        chunks = tuple(await self._adapter.build_chunks(document))
        payloads = tuple(
            [await self._adapter.build_payload(chunk) for chunk in chunks]
        )
        raw_content = _raw_content_from_document(document)
        return PreparedIngestData(
            document=document,
            chunks=chunks,
            payloads=payloads,
            raw_content=raw_content,
        )


def _raw_content_from_document(document: Any) -> bytes | None:
    metadata = getattr(document, "metadata", {}) or {}
    raw_text = metadata.get("raw_text", "")
    if not raw_text:
        return None
    return str(raw_text).encode("utf-8")
