"""Dev profile defaults for application settings.

Sits between local and production: production-shaped settings with local
endpoints, relaxed logging, and fake memory modes for a full stack on one host.
Secrets and deployment-specific credentials must be provided by env files or
process environment variables, not by this committed module.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from configs.base import (
    AppSettings as BaseAppSettings,
)
from configs.base import (
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
    "RAG_GRPC_PORT": "50051",
    "RAG_GENERATION_ENABLED": "false",
    "RAG_OBJECT_STORAGE_PROVIDER": "filesystem",
    "RAG_OBJECT_STORAGE_BASE_PATH": "~/projects/simple_agent/rag-dev/raw_storage",
    "RETRIEVAL_PLACEMENT_ENABLED": "true",
    "RETRIEVAL_PLACEMENT_ROUTING_MODE": "project_single",
    "RETRIEVAL_PLACEMENT_BUCKET_COUNT": "1",
    "RETRIEVAL_PLACEMENT_REPLICATION_FACTOR": "1",
    "RETRIEVAL_PLACEMENT_SHARD_ID": "dev-qdrant",
    "RETRIEVAL_PLACEMENT_CLUSTER_ID": "dev",
    "RAG_POSTGRES_URL": "postgresql://rag:rag@localhost:5432/rag",
    "RAG_LOG_FORMAT": "text",
    "RAG_LOG_LEVEL": "DEBUG",
    "RAG_OPS_ENABLED": "true",
    "BROKER_BOOTSTRAP_SERVERS": "127.0.0.1:9092",
    "BROKER_TOPIC_PREFIX": "qdrant-rag-dev.",
    "MEMORY_IDENTITY_MODE": "fake",
    "MEMORY_INDEX_MODE": "fake",
    "MEMORY_SEARCH_MODE": "fake",
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
    """Load settings using the dev profile unless explicitly overridden."""

    selected_profile = profile or "dev"
    selected_defaults = (
        DEFAULT_ENV if selected_profile == "dev" else profile_defaults(selected_profile)
    )
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
