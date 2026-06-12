"""Metadata normalization helpers."""

from __future__ import annotations

from typing import Any


def compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value not in (None, "")}
