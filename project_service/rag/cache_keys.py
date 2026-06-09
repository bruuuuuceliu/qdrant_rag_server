"""Cache-key builders for RAG search and generation results."""

from __future__ import annotations

import hashlib
from typing import Any

from project_service.gateway.plans import SearchPlan
from project_service.rag.retrieval_config import (
    ProjectRetrievalSettings,
    parse_retrieval_settings,
)


def _make_search_cache_key(
    plan: SearchPlan,
    settings: ProjectRetrievalSettings | None = None,
) -> str:
    settings = settings or parse_retrieval_settings(plan.config.retrieval_config)
    components = [
        plan.request.project_id,
        plan.request.user_id,
        plan.request.query,
        ",".join(sorted(plan.request.kb_ids)),
        str(plan.request.include_shared),
        plan.config.active_embedding_version,
        _make_retrieval_settings_fingerprint(settings),
    ]
    return hashlib.sha256("|".join(components).encode()).hexdigest()


def _make_retrieval_settings_fingerprint(
    settings: ProjectRetrievalSettings,
) -> str:
    components = [
        settings.mode,
        settings.fusion,
        str(settings.dense_weight),
        str(settings.bm25_weight),
        settings.bm25.sparse_vector_name,
        settings.bm25.dense_vector_name,
        settings.bm25.encoder_provider,
        settings.bm25.encoder_model,
        settings.bm25.text_field,
        str(settings.bm25.lemmatize),
        settings.bm25.index_version,
        str(settings.ner.enabled),
        settings.ner.provider,
        settings.ner.model,
        settings.ner.enrichment_version,
        str(settings.ner.boost_entities),
        str(settings.ner.entity_boost),
    ]
    return hashlib.sha256("|".join(components).encode()).hexdigest()


def _make_response_cache_key(
    project_id: str,
    user_id: str,
    query: str,
    chunks: list[dict[str, Any]],
    *,
    provider: str = "",
    model: str = "",
) -> str:
    chunk_sig = "|".join(sorted(c.get("chunk_id", "") for c in chunks))
    raw = f"{project_id}|{user_id}|{query}|{chunk_sig}|{provider}|{model}"
    return hashlib.sha256(raw.encode()).hexdigest()
