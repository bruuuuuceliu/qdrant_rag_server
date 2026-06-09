"""Project-level entity boost policy."""

from __future__ import annotations

from dataclasses import replace

from retrieval_service.services.entities import EntityMention
from retrieval_service.services.retriever import RetrievalHit


def extract_query_entity_keys(
    *,
    query_entities: list[EntityMention],
) -> set[str]:
    return {entity.key for entity in query_entities}


def apply_entity_boosts(
    hits: list[RetrievalHit],
    *,
    query_entity_keys: set[str],
    boost: float,
) -> list[RetrievalHit]:
    if not hits or not query_entity_keys or boost <= 0:
        return hits

    boosted: list[RetrievalHit] = []
    for hit in hits:
        metadata = hit.payload.get("metadata", {})
        if not isinstance(metadata, dict):
            boosted.append(hit)
            continue
        hit_keys = metadata.get("entity_keys", ())
        if not isinstance(hit_keys, (list, tuple, set)):
            boosted.append(hit)
            continue
        overlap = sorted(query_entity_keys.intersection(str(key) for key in hit_keys))
        if not overlap:
            boosted.append(hit)
            continue
        hit_metadata = dict(hit.metadata)
        hit_metadata["base_score"] = hit.score
        hit_metadata["entity_overlap"] = overlap
        boosted.append(
            replace(
                hit,
                score=hit.score + boost * len(overlap),
                metadata=hit_metadata,
            )
        )
    return sorted(boosted, key=lambda item: item.score, reverse=True)
