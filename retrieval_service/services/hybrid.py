"""Hybrid retrieval and candidate fusion."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

from retrieval_service.services.retriever import (
    RetrievalHit,
    RetrievalQuery,
    Retriever,
    RetrieverSource,
)


@dataclass(frozen=True, slots=True)
class FusionConfig:
    method: str = "rrf"
    dense_weight: float = 1.0
    bm25_weight: float = 1.0
    rrf_k: int = 60
    dedupe_key: str = "chunk_id"


class CandidateFusion:
    """Merge independent retriever result sets into one ranked list."""

    def fuse(
        self,
        result_sets: list[list[RetrievalHit]],
        *,
        config: FusionConfig,
        limit: int,
    ) -> list[RetrievalHit]:
        if config.method != "rrf":
            return self._weighted(result_sets, config=config, limit=limit)
        return self._rrf(result_sets, config=config, limit=limit)

    def _rrf(
        self,
        result_sets: list[list[RetrievalHit]],
        *,
        config: FusionConfig,
        limit: int,
    ) -> list[RetrievalHit]:
        merged: dict[str, RetrievalHit] = {}
        scores: dict[str, float] = {}
        sources: dict[str, set[str]] = {}

        for result_set in result_sets:
            for index, hit in enumerate(result_set):
                key = _dedupe_key(hit, config.dedupe_key)
                rank = hit.rank or index + 1
                weight = _source_weight(hit.source, config)
                scores[key] = scores.get(key, 0.0) + weight / (config.rrf_k + rank)
                sources.setdefault(key, set()).add(hit.source)
                if key not in merged or _payload_text_len(hit) > _payload_text_len(merged[key]):
                    merged[key] = hit

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        fused: list[RetrievalHit] = []
        for rank, (key, score) in enumerate(ranked[:limit], start=1):
            hit = merged[key]
            metadata = dict(hit.metadata)
            metadata["base_score"] = hit.score
            metadata["retrieval_sources"] = sorted(sources.get(key, ()))
            fused.append(
                replace(
                    hit,
                    score=score,
                    source="hybrid",
                    rank=rank,
                    metadata=metadata,
                )
            )
        return fused

    def _weighted(
        self,
        result_sets: list[list[RetrievalHit]],
        *,
        config: FusionConfig,
        limit: int,
    ) -> list[RetrievalHit]:
        merged: dict[str, RetrievalHit] = {}
        scores: dict[str, float] = {}
        sources: dict[str, set[str]] = {}

        for result_set in result_sets:
            normalized = _min_max_normalize(result_set)
            for hit, normalized_score in zip(result_set, normalized):
                key = _dedupe_key(hit, config.dedupe_key)
                weight = _source_weight(hit.source, config)
                scores[key] = scores.get(key, 0.0) + weight * normalized_score
                sources.setdefault(key, set()).add(hit.source)
                if key not in merged or _payload_text_len(hit) > _payload_text_len(merged[key]):
                    merged[key] = hit

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        fused: list[RetrievalHit] = []
        for rank, (key, score) in enumerate(ranked[:limit], start=1):
            hit = merged[key]
            metadata = dict(hit.metadata)
            metadata["base_score"] = hit.score
            metadata["retrieval_sources"] = sorted(sources.get(key, ()))
            fused.append(
                replace(
                    hit,
                    score=score,
                    source="hybrid",
                    rank=rank,
                    metadata=metadata,
                )
            )
        return fused


class HybridRetriever:
    """Run multiple retrievers concurrently and fuse their results."""

    source: RetrieverSource = "hybrid"

    def __init__(
        self,
        *,
        retrievers: list[Retriever],
        fusion: CandidateFusion | None = None,
        fusion_config: FusionConfig | None = None,
    ) -> None:
        if not retrievers:
            raise ValueError("at least one retriever is required")
        self._retrievers = retrievers
        self._fusion = fusion or CandidateFusion()
        self._fusion_config = fusion_config or FusionConfig()

    async def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        result_sets = await asyncio.gather(
            *[retriever.search(query) for retriever in self._retrievers]
        )
        return self._fusion.fuse(
            result_sets,
            config=self._fusion_config,
            limit=query.limit,
        )


def _source_weight(source: RetrieverSource, config: FusionConfig) -> float:
    if source == "bm25":
        return config.bm25_weight
    if source == "dense":
        return config.dense_weight
    return 1.0


def _dedupe_key(hit: RetrievalHit, preferred_key: str) -> str:
    payload = hit.payload
    for key in (preferred_key, "chunk_id", "payload_id"):
        value = payload.get(key)
        if value:
            return str(value)
    fallback: tuple[Any, ...] = (
        payload.get("project_id", ""),
        payload.get("user_id", ""),
        payload.get("kb_id", ""),
        payload.get("doc_id", ""),
        payload.get("chunk_index", ""),
        payload.get("text", ""),
    )
    return "|".join(str(part) for part in fallback)


def _payload_text_len(hit: RetrievalHit) -> int:
    return len(str(hit.payload.get("text", "")))


def _min_max_normalize(hits: list[RetrievalHit]) -> list[float]:
    if not hits:
        return []
    scores = [hit.score for hit in hits]
    low = min(scores)
    high = max(scores)
    if high == low:
        return [1.0 for _ in hits]
    return [(score - low) / (high - low) for score in scores]
