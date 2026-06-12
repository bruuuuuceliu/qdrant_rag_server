"""Section-aware chunking for ingestion output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ingestion_service.normalization import split_paragraphs
from ingestion_service.schemas import IngestedChunk, IngestedDocument, IngestedSection


@dataclass(frozen=True, slots=True)
class _ChunkUnit:
    text: str
    section_id: str
    heading: str
    metadata: dict[str, Any]
    start_page: int | None = None
    end_page: int | None = None


class SectionAwareChunker:
    """Small, deterministic, section-aware chunker for constrained workers."""

    def __init__(self, *, chunker_version: str = "v1", max_chars: int = 2400) -> None:
        self.chunker_version = chunker_version
        self.max_chars = max_chars

    def chunk(
        self,
        document: IngestedDocument,
        sections: tuple[IngestedSection, ...],
    ) -> tuple[IngestedChunk, ...]:
        units = _section_units(sections, max_chars=self.max_chars)
        packed = _pack_units(units, max_chars=self.max_chars)
        if packed:
            return tuple(
                IngestedChunk(
                    document_id=document.document_id,
                    chunk_id=f"{document.document_id}:{index}",
                    chunk_index=index,
                    text="\n\n".join(unit.text for unit in group),
                    data_type=document.data_type,
                    content_hash=document.content_hash,
                    chunker_version=self.chunker_version,
                    metadata=_chunk_metadata(group),
                )
                for index, group in enumerate(packed)
            )
        fallback = document.source_uri or document.title or document.document_id
        return (
            IngestedChunk(
                document_id=document.document_id,
                chunk_id=f"{document.document_id}:0",
                chunk_index=0,
                text=fallback,
                data_type=document.data_type,
                content_hash=document.content_hash,
                chunker_version=self.chunker_version,
            ),
        )


def _section_units(
    sections: tuple[IngestedSection, ...],
    *,
    max_chars: int,
) -> list[_ChunkUnit]:
    units: list[_ChunkUnit] = []
    for section in sections:
        start_page, end_page = _section_page_range(section)
        for paragraph in _split_large_text(section.text, max_chars):
            units.append(
                _ChunkUnit(
                    text=paragraph,
                    section_id=section.section_id,
                    heading=section.heading,
                    metadata=dict(section.metadata),
                    start_page=start_page,
                    end_page=end_page,
                )
            )
    return units


def _split_large_text(text: str, max_chars: int) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in split_paragraphs(text) or [text.strip()]:
        if len(paragraph) <= max_chars:
            paragraphs.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            paragraphs.append(paragraph[start : start + max_chars].strip())
            start += max_chars
    return [paragraph for paragraph in paragraphs if paragraph]


def _pack_units(
    units: list[_ChunkUnit],
    *,
    max_chars: int,
) -> list[list[_ChunkUnit]]:
    groups: list[list[_ChunkUnit]] = []
    current: list[_ChunkUnit] = []
    current_chars = 0
    separator_chars = 2
    for unit in units:
        next_chars = (
            len(unit.text)
            if not current
            else current_chars + separator_chars + len(unit.text)
        )
        if current and next_chars > max_chars:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(unit)
        current_chars = (
            len(unit.text)
            if current_chars == 0
            else current_chars + separator_chars + len(unit.text)
        )
    if current:
        groups.append(current)
    return groups


def _chunk_metadata(units: list[_ChunkUnit]) -> dict[str, Any]:
    metadata = _common_metadata(units)

    sections = _ordered_unique(unit.section_id for unit in units if unit.section_id)
    if len(sections) == 1:
        metadata["section"] = sections[0]
    elif sections:
        metadata["section"] = sections[0]
        metadata["sections"] = sections

    headings = _ordered_unique(unit.heading for unit in units if unit.heading)
    if len(headings) == 1:
        metadata["heading"] = headings[0]
    elif headings:
        metadata["headings"] = headings

    page_ranges = [
        (unit.start_page, unit.end_page)
        for unit in units
        if unit.start_page is not None and unit.end_page is not None
    ]
    if page_ranges:
        start_page = min(start for start, _ in page_ranges if start is not None)
        end_page = max(end for _, end in page_ranges if end is not None)
        metadata["start_page"] = start_page
        metadata["end_page"] = end_page
        if start_page == end_page:
            metadata["page_number"] = start_page

    return metadata


def _common_metadata(units: list[_ChunkUnit]) -> dict[str, Any]:
    if not units:
        return {}
    ignored = {
        "section",
        "sections",
        "heading",
        "headings",
        "page_number",
        "start_page",
        "end_page",
    }
    common: dict[str, Any] = {}
    first = units[0].metadata
    for key, value in first.items():
        if key in ignored:
            continue
        if all(unit.metadata.get(key) == value for unit in units[1:]):
            common[key] = value
    return common


def _section_page_range(section: IngestedSection) -> tuple[int | None, int | None]:
    if section.page_number is not None:
        return section.page_number, section.page_number
    start_page = _coerce_int(section.metadata.get("start_page"))
    end_page = _coerce_int(section.metadata.get("end_page"))
    page_number = _coerce_int(section.metadata.get("page_number"))
    if start_page is not None or end_page is not None:
        start = start_page if start_page is not None else end_page
        end = end_page if end_page is not None else start_page
        return start, end
    if page_number is not None:
        return page_number, page_number
    return None, None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
