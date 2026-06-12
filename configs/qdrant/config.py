"""Qdrant configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from configs.config import get_optional_value, get_value


CONFIG_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class QdrantSettings:
    url: str | None
    host: str
    port: int


def load_qdrant_settings(values: dict[str, str]) -> QdrantSettings:
    return QdrantSettings(
        url=get_optional_value(values, "RAG_QDRANT_URL"),
        host=get_value(values, "RAG_QDRANT_HOST", "localhost"),
        port=int(get_value(values, "RAG_QDRANT_PORT", "6333")),
    )
