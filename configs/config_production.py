"""Production profile defaults for application settings.

Secrets and deployment-specific credentials must be provided by env files or
process environment variables, not by this committed module. This file also
exports the active config API, so it can be copied to ``configs/config.py`` for
deployments that promote exactly one config file.
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
    "RAG_CONFIG_DB_PATH": "/var/lib/retrieval_service/config.db",
    "RAG_RESPONSE_CACHE_DB_PATH": "/var/lib/retrieval_service/response_cache.db",
    "RAG_GRPC_PORT": "50051",
    "RETRIEVAL_HTTP_HOST": "0.0.0.0",
    "RETRIEVAL_HTTP_PORT": "8081",
    "RETRIEVAL_HTTP_READ_TIMEOUT": "5.0",
    "MANAGER_RETRIEVAL_HTTP_BASE_URL": "http://retrieval-service:8081",
    "MANAGER_RETRIEVAL_HTTP_TIMEOUT": "30",
    "RAG_MAX_PER_PROJECT": "20",
    "RAG_MAX_PER_USER": "5",
    "RAG_MAX_CONCURRENT_SEARCHES": "32",
    "RAG_MAX_CONCURRENT_INGEST_SCHEDULES": "32",
    "RAG_INGEST_WORKERS": "4",
    "RAG_INGEST_QUEUE_MAXSIZE": "100",
    "RAG_INGEST_JOB_DB_PATH": "/var/lib/retrieval_service/ingestion_jobs.db",
    "RAG_INGEST_EVENT_TOPIC": "ingestion.events",
    "RAG_INGEST_EVENT_QUEUE_MAXSIZE": "1000",
    "WORKFLOW_LOG_SERVICE_ENABLED": "true",
    "WORKFLOW_LOG_SERVICE_NAME": "workflow_log_service",
    "WORKFLOW_LOG_TOPIC": "ingestion.events",
    "WORKFLOW_LOG_DB_PATH": "/var/lib/retrieval_service/workflow_log.db",
    "RAG_GENERATION_ENABLED": "false",
    "RAG_OBJECT_STORAGE_PROVIDER": "filesystem",
    "RAG_OBJECT_STORAGE_BASE_PATH": "/var/lib/retrieval_service/raw_storage",
    "RETRIEVAL_PLACEMENT_ENABLED": "true",
    "RETRIEVAL_PLACEMENT_DB_PATH": "/var/lib/retrieval_service/placement.db",
    "RETRIEVAL_PLACEMENT_ROUTING_MODE": "project_single",
    "RETRIEVAL_PLACEMENT_BUCKET_COUNT": "1",
    "RETRIEVAL_PLACEMENT_REPLICATION_FACTOR": "1",
    "RETRIEVAL_PLACEMENT_SHARD_ID": "retrieval-primary",
    "RETRIEVAL_PLACEMENT_CLUSTER_ID": "retrieval-cluster",
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
    """Load settings using the production profile unless explicitly overridden."""

    selected_profile = profile or "production"
    selected_defaults = (
        DEFAULT_ENV if selected_profile == "production" else profile_defaults(selected_profile)
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
