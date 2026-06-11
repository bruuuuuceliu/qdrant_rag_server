"""Compatibility shim for reusable entity boost ranking helpers."""

from retrieval_service.ranking.entity_boost import (
    apply_entity_boosts,
    extract_query_entity_keys,
)

__all__ = ["apply_entity_boosts", "extract_query_entity_keys"]
