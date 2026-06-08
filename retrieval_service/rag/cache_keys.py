"""Cache-key builders for RAG search and generation results."""

from __future__ import annotations

import hashlib
from typing import Any

from retrieval_service.gateway.plans import SearchPlan


def _make_search_cache_key(plan: SearchPlan) -> str:
    components = [
        plan.request.project_id,
        plan.request.user_id,
        plan.request.query,
        ",".join(sorted(plan.request.kb_ids)),
        str(plan.request.include_shared),
        plan.config.active_embedding_version,
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
