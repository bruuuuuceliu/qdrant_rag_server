"""Local profile defaults for application settings.

These values are safe defaults for development. Secrets should stay in local
env files or process environment variables, not in this module. This file also
exports the active config API, so it can be copied to ``configs/config.py`` for
local-only deployments without breaking runtime imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from configs.base import (
    AppSettings as BaseAppSettings,
    get_bool_value,
    get_float_value,
    get_int_value,
    get_optional_value,
    get_positive_int_value,
    get_value,
    load_settings_from_defaults,
    profile_defaults,
    profile_env,
    profile_name_from_env,
    read_env_file,
)

DEFAULT_ENV: dict[str, str] = {
    "RAG_RESPONSE_CACHE_DB_PATH": "/var/lib/rag/response_cache.db",
    "RAG_GRPC_PORT": "50051",
    "RAG_QDRANT_HOST": "localhost",
    "RAG_QDRANT_PORT": "6333",
    "BM25_SPARSE_VECTOR_NAME": "bm25",
    "BM25_DENSE_VECTOR_NAME": "dense",
    "BM25_ENCODER_PROVIDER": "fastembed",
    "BM25_ENCODER_MODEL": "Qdrant/bm25",
    "BM25_TEXT_FIELD": "text_lemmatized",
    "BM25_LEMMATIZE": "true",
    "BM25_INDEX_VERSION": "qdrant_bm25_v1",
    "RAG_NER_PROVIDER": "disabled",
    "RAG_NER_MODEL": "en_core_web_sm",
    "RAG_EMBEDDING_PROVIDER": "local",
    "RAG_EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5",
    "RAG_EMBEDDING_DEVICE": "cpu",
    "RAG_EMBEDDING_DIMENSION": "768",
    "RAG_EMBEDDING_BASE_URL": "https://openrouter.ai/api/v1/embeddings",
    "RAG_GENERATION_ENABLED": "false",
    "RAG_OBJECT_STORAGE_PROVIDER": "filesystem",
    "RAG_OBJECT_STORAGE_BASE_PATH": "/tmp/qdrant_rag/raw_storage",
    "RETRIEVAL_PLACEMENT_ENABLED": "true",
    "RETRIEVAL_PLACEMENT_DB_PATH": "/var/lib/rag/placement.db",
    "RETRIEVAL_PLACEMENT_ROUTING_MODE": "project_single",
    "RETRIEVAL_PLACEMENT_BUCKET_COUNT": "1",
    "RETRIEVAL_PLACEMENT_REPLICATION_FACTOR": "1",
    "RETRIEVAL_PLACEMENT_SHARD_ID": "local-qdrant",
    "RETRIEVAL_PLACEMENT_CLUSTER_ID": "local",
}


class AppSettings(BaseAppSettings):
    @classmethod
    def from_env(
        cls,
        *,
        profile: str | None = None,
        env_file: str | Path | None = None,
        component_env_files: Sequence[str | Path] = (),
    ) -> BaseAppSettings:
        return load_settings(
            profile=profile,
            env_file=env_file,
            component_env_files=component_env_files,
        )


def load_settings(
    *,
    profile: str | None = None,
    env_file: str | Path | None = None,
    component_env_files: Sequence[str | Path] = (),
) -> AppSettings:
    """Load settings using the local profile unless explicitly overridden."""

    selected_profile = profile or "local"
    selected_defaults = DEFAULT_ENV if selected_profile == "local" else profile_defaults(selected_profile)
    return load_settings_from_defaults(
        profile=selected_profile,
        defaults=selected_defaults,
        env_file=env_file,
        component_env_files=component_env_files,
    )


__all__ = [
    "AppSettings",
    "DEFAULT_ENV",
    "get_bool_value",
    "get_float_value",
    "get_int_value",
    "get_optional_value",
    "get_positive_int_value",
    "get_value",
    "load_settings_from_defaults",
    "load_settings",
    "profile_defaults",
    "profile_env",
    "profile_name_from_env",
    "read_env_file",
]
