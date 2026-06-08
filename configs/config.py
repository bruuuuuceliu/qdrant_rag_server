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
    generation_provider: str = "openrouter"
    generation_model: str = "openai/gpt-4o-mini"
    generation_api_key: str = ""
    generation_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    generation_max_tokens: int = 1024
    generation_temperature: float = 0.7

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

    from configs.embeddings.config import load_embedding_settings
    from configs.generation.config import load_generation_settings
    from configs.qdrant.config import load_qdrant_settings

    embedding_settings = load_embedding_settings(values)
    generation_settings = load_generation_settings(values)
    qdrant_settings = load_qdrant_settings(values)

    return AppSettings(
        config_db_path=Path(get_value(values, "RAG_CONFIG_DB_PATH", "/var/lib/rag/config.db")),
        response_cache_db_path=Path(
            get_value(values, "RAG_RESPONSE_CACHE_DB_PATH", "/var/lib/rag/response_cache.db")
        ),
        grpc_port=get_int_value(values, "RAG_GRPC_PORT", 50051),
        qdrant_url=qdrant_settings.url,
        qdrant_host=qdrant_settings.host,
        qdrant_port=qdrant_settings.port,
        max_per_project=get_int_value(values, "RAG_MAX_PER_PROJECT", 20),
        max_per_user=get_int_value(values, "RAG_MAX_PER_USER", 5),
        ingest_worker_count=get_int_value(values, "RAG_INGEST_WORKERS", 4),
        embedding_provider=embedding_settings.provider,
        embedding_model=embedding_settings.model,
        embedding_device=embedding_settings.device,
        embedding_api_key=embedding_settings.api_key,
        embedding_base_url=embedding_settings.base_url,
        embedding_dimension=embedding_settings.dimension,
        generation_enabled=generation_settings.enabled,
        generation_provider=generation_settings.provider,
        generation_model=generation_settings.model,
        generation_api_key=generation_settings.api_key,
        generation_base_url=generation_settings.base_url,
        generation_max_tokens=generation_settings.max_tokens,
        generation_temperature=generation_settings.temperature,
    )


def _profile_env(profile: str) -> Path:
    return CONFIG_ROOT / f"{profile}.env"


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


def get_value(values: dict[str, str], name: str, default: str) -> str:
    return values.get(name, default)


def get_optional_value(values: dict[str, str], name: str) -> str | None:
    value = values.get(name)
    if value is None or not value.strip():
        return None
    return value


def get_int_value(values: dict[str, str], name: str, default: int) -> int:
    value = values.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def get_bool_value(values: dict[str, str], name: str, default: bool) -> bool:
    value = values.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")
