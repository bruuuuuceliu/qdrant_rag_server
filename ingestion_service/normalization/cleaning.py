"""Conservative document cleaning before chunking."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, replace
from typing import Any

from ingestion_service.normalization.text import normalize_text
from ingestion_service.schemas import CleaningPolicy, IngestedSection


@dataclass(frozen=True, slots=True)
class DroppedSection:
    section_id: str
    reason: str
    text_preview: str = ""
    start_page: int | None = None
    end_page: int | None = None
    noise_score: float = 0.0


@dataclass(frozen=True, slots=True)
class CleaningResult:
    sections: tuple[IngestedSection, ...]
    dropped_sections: tuple[DroppedSection, ...] = ()
    stats: dict[str, Any] | None = None


class DocumentCleaner:
    """Clean parsed sections while preserving traceability metadata."""

    def clean(
        self,
        sections: tuple[IngestedSection, ...],
        *,
        policy: CleaningPolicy,
    ) -> CleaningResult:
        if not policy.enabled:
            return CleaningResult(
                sections=sections,
                stats={
                    "cleaning_enabled": False,
                    "cleaning_version": policy.cleaning_version,
                    "input_sections": len(sections),
                    "output_sections": len(sections),
                    "dropped_sections": 0,
                },
            )

        repeated_lines = _find_repeated_edge_lines(sections, policy=policy)
        cleaned: list[IngestedSection] = []
        dropped: list[DroppedSection] = []
        removed_repeated_lines_total = 0

        for section in sections:
            text = section.text
            if policy.remove_control_chars:
                text = _remove_control_chars(text)
            if policy.repair_pdf_line_wraps:
                text = _repair_pdf_line_wraps(text)
            text = normalize_text(text)

            removed_lines = 0
            if policy.remove_repeated_page_lines and repeated_lines:
                text, removed_lines = _remove_repeated_lines(text, repeated_lines)
                removed_repeated_lines_total += removed_lines

            text = normalize_text(text)
            noise_score = _noise_score(text)
            reason = _drop_reason(text, noise_score, policy)
            if reason:
                dropped.append(
                    DroppedSection(
                        section_id=section.section_id,
                        reason=reason,
                        text_preview=text[:160],
                        start_page=_section_start_page(section),
                        end_page=_section_end_page(section),
                        noise_score=noise_score,
                    )
                )
                continue

            metadata = dict(section.metadata)
            metadata["cleaning_version"] = policy.cleaning_version
            metadata["cleaning_applied"] = True
            metadata["noise_score"] = round(noise_score, 4)
            if removed_lines:
                metadata["removed_repeated_lines"] = removed_lines

            cleaned.append(replace(section, text=text, metadata=metadata))

        return CleaningResult(
            sections=tuple(cleaned),
            dropped_sections=tuple(dropped),
            stats={
                "cleaning_enabled": True,
                "cleaning_version": policy.cleaning_version,
                "input_sections": len(sections),
                "output_sections": len(cleaned),
                "dropped_sections": len(dropped),
                "removed_repeated_lines": removed_repeated_lines_total,
                "repeated_line_count": len(repeated_lines),
            },
        )


def _remove_control_chars(text: str) -> str:
    return "".join(
        char
        if char in {"\n", "\t"} or not unicodedata_category_startswith(char, "C")
        else " "
        for char in text
    )


def unicodedata_category_startswith(char: str, prefix: str) -> bool:
    import unicodedata

    return unicodedata.category(char).startswith(prefix)


def _repair_pdf_line_wraps(text: str) -> str:
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"(?<=[^\n。！？.!?;；:：])\n(?=[^\n\s])", " ", text)
    return text


def _find_repeated_edge_lines(
    sections: tuple[IngestedSection, ...],
    *,
    policy: CleaningPolicy,
) -> set[str]:
    page_sections = [section for section in sections if _section_start_page(section) is not None]
    if len(page_sections) < policy.repeated_line_min_pages:
        return set()

    counts: dict[str, int] = {}
    for section in page_sections:
        candidates = _edge_lines(section.text, edge_lines=policy.repeated_line_edge_lines)
        for line in set(candidates):
            counts[line] = counts.get(line, 0) + 1

    return {
        line
        for line, count in counts.items()
        if count >= policy.repeated_line_min_pages and not _looks_like_body_line(line)
    }


def _edge_lines(text: str, *, edge_lines: int) -> list[str]:
    lines = [_canonical_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []
    return [*lines[:edge_lines], *lines[-edge_lines:]]


def _canonical_line(line: str) -> str:
    return normalize_text(line).strip()


def _looks_like_body_line(line: str) -> bool:
    words = line.split()
    if len(words) >= 8:
        return True
    return len(line) > 80


def _remove_repeated_lines(text: str, repeated_lines: set[str]) -> tuple[str, int]:
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        if _canonical_line(line) in repeated_lines:
            removed += 1
            continue
        kept.append(line)
    return "\n".join(kept), removed


def _noise_score(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 1.0
    chars = [char for char in stripped if not char.isspace()]
    if not chars:
        return 1.0
    symbols = sum(1 for char in chars if char in string.punctuation)
    alnum = sum(1 for char in chars if char.isalnum())
    symbol_ratio = symbols / len(chars)
    alpha_ratio = alnum / len(chars)
    short_penalty = max(0.0, (20 - len(stripped)) / 20)
    low_alpha_penalty = max(0.0, 0.45 - alpha_ratio)
    return min(1.0, symbol_ratio * 0.6 + short_penalty * 0.3 + low_alpha_penalty * 0.4)


def _drop_reason(text: str, noise_score: float, policy: CleaningPolicy) -> str:
    if policy.drop_empty_sections and not text.strip():
        return "empty"
    if not policy.drop_short_noise_sections:
        return ""
    if len(text.strip()) < policy.min_text_chars and noise_score >= policy.max_symbol_ratio:
        return "short_noise"
    if noise_score >= 0.95:
        return "high_noise"
    return ""


def _section_start_page(section: IngestedSection) -> int | None:
    if section.page_number is not None:
        return section.page_number
    return _coerce_int(section.metadata.get("start_page") or section.metadata.get("page_number"))


def _section_end_page(section: IngestedSection) -> int | None:
    if section.page_number is not None:
        return section.page_number
    return _coerce_int(section.metadata.get("end_page") or section.metadata.get("page_number"))


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None
