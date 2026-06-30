"""Shared configuration loading primitives.

Profile entrypoints such as ``configs.config``, ``configs.config_local``, and
``configs.config_production`` import from this module so each profile file can
also be promoted to the active ``configs/config.py`` file without losing the
public loader API.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path


CONFIG_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class AppSettings:
    response_cache_db_path: Path
    grpc_port: int
    qdrant_url: str | None
    qdrant_host: str
    qdrant_port: int
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
    bm25_sparse_vector_name: str = "bm25"
    bm25_dense_vector_name: str = "dense"
    bm25_encoder_provider: str = "fastembed"
    bm25_encoder_model: str = "Qdrant/bm25"
    bm25_text_field: str = "text_lemmatized"
    bm25_lemmatize: bool = True
    bm25_index_version: str = "qdrant_bm25_v1"
    ner_provider: str = "disabled"
    ner_model: str = "en_core_web_sm"
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_device: str = "cpu"
    object_storage_provider: str = "filesystem"
    object_storage_base_path: Path = Path("/tmp/qdrant_rag/raw_storage")
    retrieval_placement_enabled: bool = True
    retrieval_placement_db_path: Path = Path("/tmp/qdrant_rag/placement.db")
    retrieval_placement_routing_mode: str = "project_single"
    retrieval_placement_bucket_count: int = 1
    retrieval_placement_replication_factor: int = 1
    retrieval_placement_shard_id: str = "local-qdrant"
    retrieval_placement_cluster_id: str = "local"

    @classmethod
    def from_env(
        cls,
        *,
        profile: str | None = None,
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
    profile: str | None = None,
    env_file: str | Path | None = None,
    component_env_files: Sequence[str | Path] = (),
) -> AppSettings:
    profile_name = profile_name_from_env(profile)
    return load_settings_from_defaults(
        profile=profile_name,
        defaults=profile_defaults(profile_name),
        env_file=env_file,
        component_env_files=component_env_files,
    )


def load_settings_from_defaults(
    *,
    profile: str,
    defaults: dict[str, str],
    env_file: str | Path | None = None,
    component_env_files: Sequence[str | Path] = (),
) -> AppSettings:
    values: dict[str, str] = {str(key): str(value) for key, value in defaults.items()}

    selected_env = Path(env_file) if env_file is not None else profile_env(profile)
    for path in (selected_env, *[Path(p) for p in component_env_files]):
        values.update(read_env_file(path))

    values.update(os.environ)

    from configs.embeddings.config import load_embedding_settings
    from configs.generation.config import load_generation_settings
    from configs.qdrant.config import load_qdrant_settings
    from configs.retrieval.config import load_retrieval_component_settings
    embedding_settings = load_embedding_settings(values)
    generation_settings = load_generation_settings(values)
    qdrant_settings = load_qdrant_settings(values)
    retrieval_settings = load_retrieval_component_settings(values)

    return AppSettings(
        response_cache_db_path=Path(
            get_value(values, "RAG_RESPONSE_CACHE_DB_PATH", "/var/lib/rag/response_cache.db")
        ),
        grpc_port=get_int_value(values, "RAG_GRPC_PORT", 50051),
        qdrant_url=qdrant_settings.url,
        qdrant_host=qdrant_settings.host,
        qdrant_port=qdrant_settings.port,
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
        bm25_sparse_vector_name=retrieval_settings.bm25_sparse_vector_name,
        bm25_dense_vector_name=retrieval_settings.bm25_dense_vector_name,
        bm25_encoder_provider=retrieval_settings.bm25_encoder_provider,
        bm25_encoder_model=retrieval_settings.bm25_encoder_model,
        bm25_text_field=retrieval_settings.bm25_text_field,
        bm25_lemmatize=retrieval_settings.bm25_lemmatize,
        bm25_index_version=retrieval_settings.bm25_index_version,
        ner_provider=retrieval_settings.ner_provider,
        ner_model=retrieval_settings.ner_model,
        rerank_enabled=get_bool_value(values, "RAG_RERANK_ENABLED", False),
        rerank_model=get_value(values, "RAG_RERANK_MODEL", "BAAI/bge-reranker-base"),
        rerank_device=get_value(values, "RAG_RERANK_DEVICE", "cpu"),
        object_storage_provider=get_value(values, "RAG_OBJECT_STORAGE_PROVIDER", "filesystem"),
        object_storage_base_path=Path(
            get_value(values, "RAG_OBJECT_STORAGE_BASE_PATH", "/tmp/qdrant_rag/raw_storage")
        ),
        retrieval_placement_enabled=get_bool_value(
            values,
            "RETRIEVAL_PLACEMENT_ENABLED",
            True,
        ),
        retrieval_placement_db_path=Path(
            get_value(
                values,
                "RETRIEVAL_PLACEMENT_DB_PATH",
                "/tmp/qdrant_rag/placement.db",
            )
        ),
        retrieval_placement_routing_mode=get_value(
            values,
            "RETRIEVAL_PLACEMENT_ROUTING_MODE",
            "project_single",
        ),
        retrieval_placement_bucket_count=get_positive_int_value(
            values,
            "RETRIEVAL_PLACEMENT_BUCKET_COUNT",
            1,
        ),
        retrieval_placement_replication_factor=get_positive_int_value(
            values,
            "RETRIEVAL_PLACEMENT_REPLICATION_FACTOR",
            1,
        ),
        retrieval_placement_shard_id=get_value(
            values,
            "RETRIEVAL_PLACEMENT_SHARD_ID",
            "local-qdrant",
        ),
        retrieval_placement_cluster_id=get_value(
            values,
            "RETRIEVAL_PLACEMENT_CLUSTER_ID",
            "local",
        ),
    )


def profile_env(profile: str) -> Path:
    return CONFIG_ROOT / f"{profile}.env"


def profile_name_from_env(profile: str | None) -> str:
    profile_name = (profile or os.environ.get("RAG_CONFIG_PROFILE") or "local").strip().lower()
    if not profile_name:
        raise ValueError("RAG_CONFIG_PROFILE must not be empty")
    if not profile_name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("RAG_CONFIG_PROFILE may contain only letters, numbers, '-' and '_'")
    return profile_name.replace("-", "_")


def profile_defaults(profile: str) -> dict[str, str]:
    module_name = f"configs.config_{profile}"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise ValueError(f"unknown config profile: {profile}") from exc
        raise
    defaults = getattr(module, "DEFAULT_ENV", {})
    if not isinstance(defaults, dict):
        raise TypeError(f"{module_name}.DEFAULT_ENV must be a dict")
    return {str(key): str(value) for key, value in defaults.items()}


def read_env_file(path: Path) -> dict[str, str]:
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


def get_float_value(values: dict[str, str], name: str, default: float) -> float:
    value = values.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def get_positive_int_value(values: dict[str, str], name: str, default: int) -> int:
    value = get_int_value(values, name, default)
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


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
