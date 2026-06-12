"""Runtime capability detection for ingestion routing."""

from __future__ import annotations

import importlib.util


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


class RuntimeCapabilities:
    """Lightweight installed-feature checks."""

    @property
    def has_pymupdf(self) -> bool:
        return module_available("fitz")

    @property
    def has_pypdf(self) -> bool:
        return module_available("pypdf")

    @property
    def has_docling(self) -> bool:
        return module_available("docling")
