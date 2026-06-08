"""Application configuration loading for the retrieval service.

Environment and private values flow through this module:

    .env files -> AppSettings -> runtime wiring

Runtime service code should receive typed settings and avoid reading
environment variables directly.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


CONFIG_ROOT = Path(__file__).resolve().parent
DEFAULT_EMBEDDING_BASE_URL = "https://openrouter.ai/api/v1/embeddings"


@dataclass(frozen=True, slots=True)
class AppSettings:
    config_db_path: Path
    response_cache_db_path: Path
    grpc_port: int
    qdrant_url: str | None
    qdrant_host: str
    qdrant_port: int
    max_per_project: int
    max_per_user: int
    ingest_worker_count: int
    embedding_provider: str
    embedding_model: str
    embedding_device: str
    embedding_api_key: str
    embedding_base_url: str
    embedding_dimension: int
    generation_enabled: bool

    @classmethod
    def from_env(
        cls,
        *,
        profile: str = "local",
        env_file: str | Path | None = None,
        component_env_files: Sequence[str | Path] = (),
    ) -> AppSettings:
        return load_settings(
            profile=profile,
            env_file=env_file,
            component_env_files=component_env_files,
        )


def load_settings(
    *,
    profile: str = "local",
    env_file: str | Path | None = None,
    component_env_files: Sequence[str | Path] = (),
) -> AppSettings:
    values: dict[str, str] = {}

    selected_env = Path(env_file) if env_file is not None else _profile_env(profile)
    for path in (selected_env, *[Path(p) for p in component_env_files]):
        values.update(_read_env_file(path))

    values.update(os.environ)

    return AppSettings(
        config_db_path=Path(_get(values, "RAG_CONFIG_DB_PATH", "/var/lib/rag/config.db")),
        response_cache_db_path=Path(
            _get(values, "RAG_RESPONSE_CACHE_DB_PATH", "/var/lib/rag/response_cache.db")
        ),
        grpc_port=_get_int(values, "RAG_GRPC_PORT", 50051),
        qdrant_url=_optional(values, "RAG_QDRANT_URL"),
        qdrant_host=_get(values, "RAG_QDRANT_HOST", "localhost"),
        qdrant_port=_get_int(values, "RAG_QDRANT_PORT", 6333),
        max_per_project=_get_int(values, "RAG_MAX_PER_PROJECT", 20),
        max_per_user=_get_int(values, "RAG_MAX_PER_USER", 5),
        ingest_worker_count=_get_int(values, "RAG_INGEST_WORKERS", 4),
        embedding_provider=_get(values, "RAG_EMBEDDING_PROVIDER", "local"),
        embedding_model=_get(values, "RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"),
        embedding_device=_get(values, "RAG_EMBEDDING_DEVICE", "cpu"),
        embedding_api_key=_get(values, "RAG_EMBEDDING_API_KEY", ""),
        embedding_base_url=_get(
            values,
            "RAG_EMBEDDING_BASE_URL",
            DEFAULT_EMBEDDING_BASE_URL,
        ),
        embedding_dimension=_get_int(values, "RAG_EMBEDDING_DIMENSION", 768),
        generation_enabled=_get_bool(values, "RAG_GENERATION_ENABLED", False),
    )


def _profile_env(profile: str) -> Path:
    return CONFIG_ROOT / "envs" / f"{profile}.env"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _get(values: dict[str, str], name: str, default: str) -> str:
    return values.get(name, default)


def _optional(values: dict[str, str], name: str) -> str | None:
    value = values.get(name)
    if value is None or not value.strip():
        return None
    return value


def _get_int(values: dict[str, str], name: str, default: int) -> int:
    value = values.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _get_bool(values: dict[str, str], name: str, default: bool) -> bool:
    value = values.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")
