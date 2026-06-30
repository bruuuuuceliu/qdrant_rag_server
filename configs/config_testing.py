"""Testing profile defaults for application settings."""

from __future__ import annotations

from configs.config_local import DEFAULT_ENV as LOCAL_DEFAULT_ENV


DEFAULT_ENV: dict[str, str] = {
    **LOCAL_DEFAULT_ENV,
    "RAG_RESPONSE_CACHE_DB_PATH": ":memory:",
    "RETRIEVAL_PLACEMENT_DB_PATH": ":memory:",
}
