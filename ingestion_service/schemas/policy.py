"""Policy and resource-budget schemas for ingestion routing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CleaningPolicy:
    enabled: bool = True
    cleaning_version: str = "v1"
    remove_control_chars: bool = True
    repair_pdf_line_wraps: bool = True
    remove_repeated_page_lines: bool = True
    drop_empty_sections: bool = True
    drop_short_noise_sections: bool = True
    min_text_chars: int = 20
    max_symbol_ratio: float = 0.35
    repeated_line_min_pages: int = 3
    repeated_line_edge_lines: int = 2


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    resource_tier: str = "minimal"
    max_source_bytes: int = 10 * 1024 * 1024
    max_pages: int = 100
    max_slides: int = 100
    max_sheets: int = 20
    max_rows: int = 10000
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class DocumentHandlingPolicy:
    allowed_content_types: tuple[str, ...] = ()
    allowed_extensions: tuple[str, ...] = ()
    allowed_schemes: tuple[str, ...] = ("", "file", "http", "https")
    allowed_domains: tuple[str, ...] = ()
    resource_tier: str = "minimal"
    allow_local_files: bool = True
    allow_docling: bool = False
    allow_docling_ocr: bool = False
    allow_docling_vlm: bool = False
    budget: ResourceBudget = ResourceBudget()
    cleaning: CleaningPolicy = CleaningPolicy()

    def normalized_extensions(self) -> tuple[str, ...]:
        return tuple(_normalize_ext(value) for value in self.allowed_extensions)


def _normalize_ext(value: str) -> str:
    value = value.strip().lower()
    if value and not value.startswith("."):
        return f".{value}"
    return value
