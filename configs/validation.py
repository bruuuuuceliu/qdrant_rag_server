"""Configuration validation helpers for deployment readiness checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from configs.base import AppSettings


@dataclass(frozen=True, slots=True)
class ConfigValidationIssue:
    field: str
    message: str
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class ConfigValidationResult:
    issues: tuple[ConfigValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def raise_for_errors(self) -> None:
        errors = [issue for issue in self.issues if issue.severity == "error"]
        if errors:
            details = "; ".join(f"{issue.field}: {issue.message}" for issue in errors)
            raise ValueError(f"configuration validation failed: {details}")


def validate_settings(
    settings: AppSettings,
    *,
    profile: str = "local",
) -> ConfigValidationResult:
    """Validate settings without opening network connections or files."""

    normalized_profile = profile.strip().lower().replace("-", "_")
    issues: list[ConfigValidationIssue] = []

    _validate_qdrant(settings, issues)
    _validate_urls(settings, issues)
    _validate_paths(settings, issues)
    _validate_modes(settings, issues)

    if normalized_profile == "production":
        _validate_production(settings, issues)

    return ConfigValidationResult(tuple(issues))


def validate_settings_or_raise(
    settings: AppSettings,
    *,
    profile: str = "local",
) -> None:
    validate_settings(settings, profile=profile).raise_for_errors()


def _validate_qdrant(
    settings: AppSettings,
    issues: list[ConfigValidationIssue],
) -> None:
    if settings.qdrant_url:
        parsed = urlparse(settings.qdrant_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            issues.append(
                ConfigValidationIssue(
                    "qdrant_url",
                    "must be an http(s) URL when set",
                )
            )
        return
    if not settings.qdrant_host.strip():
        issues.append(ConfigValidationIssue("qdrant_host", "must not be empty"))
    if not (1 <= settings.qdrant_port <= 65535):
        issues.append(ConfigValidationIssue("qdrant_port", "must be between 1 and 65535"))


def _validate_urls(
    settings: AppSettings,
    issues: list[ConfigValidationIssue],
) -> None:
    if settings.embedding_base_url:
        parsed = urlparse(settings.embedding_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            issues.append(
                ConfigValidationIssue(
                    "embedding_base_url",
                    "must be an http(s) URL when set",
                )
            )
    if settings.generation_enabled:
        parsed = urlparse(settings.generation_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            issues.append(
                ConfigValidationIssue(
                    "generation_base_url",
                    "must be an http(s) URL when generation is enabled",
                )
            )


def _validate_paths(
    settings: AppSettings,
    issues: list[ConfigValidationIssue],
) -> None:
    path_fields = {
        "config_db_path": settings.config_db_path,
        "response_cache_db_path": settings.response_cache_db_path,
        "ingest_job_db_path": settings.ingest_job_db_path,
        "workflow_log_db_path": settings.workflow_log_db_path,
        "retrieval_placement_db_path": settings.retrieval_placement_db_path,
    }
    for field, path in path_fields.items():
        if str(path) == ":memory:":
            continue
        if not path.is_absolute():
            issues.append(ConfigValidationIssue(field, "must be an absolute path"))

    if settings.object_storage_provider == "filesystem":
        if not settings.object_storage_base_path.is_absolute():
            issues.append(
                ConfigValidationIssue(
                    "object_storage_base_path",
                    "must be an absolute path for filesystem storage",
                )
            )


def _validate_modes(
    settings: AppSettings,
    issues: list[ConfigValidationIssue],
) -> None:
    if settings.object_storage_provider not in {"filesystem", "memory"}:
        issues.append(
            ConfigValidationIssue(
                "object_storage_provider",
                "must be one of: filesystem, memory",
            )
        )
    if settings.retrieval_placement_replication_factor < 1:
        issues.append(
            ConfigValidationIssue(
                "retrieval_placement_replication_factor",
                "must be at least 1",
            )
        )
    if settings.retrieval_placement_bucket_count < 1:
        issues.append(
            ConfigValidationIssue(
                "retrieval_placement_bucket_count",
                "must be at least 1",
            )
        )


def _validate_production(
    settings: AppSettings,
    issues: list[ConfigValidationIssue],
) -> None:
    if settings.embedding_provider != "local" and not settings.embedding_api_key:
        issues.append(
            ConfigValidationIssue(
                "embedding_api_key",
                "is required in production for remote embedding providers",
            )
        )
    if settings.generation_enabled and not settings.generation_api_key:
        issues.append(
            ConfigValidationIssue(
                "generation_api_key",
                "is required in production when generation is enabled",
            )
        )
    local_hosts = {"localhost", "127.0.0.1", "0.0.0.0"}
    if not settings.qdrant_url and settings.qdrant_host in local_hosts:
        issues.append(
            ConfigValidationIssue(
                "qdrant_host",
                "should point at a deployed Qdrant service in production",
                severity="warning",
            )
        )
    for field in (
        "config_db_path",
        "response_cache_db_path",
        "ingest_job_db_path",
        "workflow_log_db_path",
        "retrieval_placement_db_path",
    ):
        value = getattr(settings, field)
        if isinstance(value, Path) and str(value) == ":memory:":
            issues.append(
                ConfigValidationIssue(field, "must not use :memory: in production")
            )
