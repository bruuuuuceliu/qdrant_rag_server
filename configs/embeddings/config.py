"""Embedding configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from configs.config import get_value


CONFIG_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class EmbeddingSettings:
    provider: str
    model: str
    device: str
    api_key: str
    base_url: str
    dimension: int


def load_embedding_settings(values: dict[str, str]) -> EmbeddingSettings:
    return EmbeddingSettings(
        provider=get_value(values, "RAG_EMBEDDING_PROVIDER", "local"),
        model=get_value(values, "RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"),
        device=get_value(values, "RAG_EMBEDDING_DEVICE", "cpu"),
        api_key=get_value(values, "RAG_EMBEDDING_API_KEY", ""),
        base_url=get_value(
            values,
            "RAG_EMBEDDING_BASE_URL",
            "https://openrouter.ai/api/v1/embeddings",
        ),
        dimension=int(get_value(values, "RAG_EMBEDDING_DIMENSION", "768")),
    )
