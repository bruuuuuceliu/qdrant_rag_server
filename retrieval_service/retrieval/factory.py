"""Reusable retriever selection."""

from __future__ import annotations

from retrieval_service.retrieval.config import ProjectRetrievalSettings
from retrieval_service.services.hybrid import CandidateFusion, FusionConfig, HybridRetriever
from retrieval_service.services.retriever import Retriever


class ProjectRetrieverFactory:
    """Select low-level retrievers from retrieval settings."""

    def __init__(
        self,
        *,
        dense_retriever: Retriever,
        bm25_retriever: Retriever | None = None,
        fusion: CandidateFusion | None = None,
    ) -> None:
        self._dense_retriever = dense_retriever
        self._bm25_retriever = bm25_retriever
        self._fusion = fusion or CandidateFusion()

    def build(self, *, settings: ProjectRetrievalSettings) -> Retriever:
        if settings.mode == "dense":
            return self._dense_retriever
        if settings.mode == "bm25":
            return self._require_bm25()
        if settings.mode == "hybrid":
            return HybridRetriever(
                retrievers=[self._dense_retriever, self._require_bm25()],
                fusion=self._fusion,
                fusion_config=FusionConfig(
                    method=settings.fusion,
                    dense_weight=settings.dense_weight,
                    bm25_weight=settings.bm25_weight,
                ),
            )
        raise ValueError(f"unsupported retrieval mode {settings.mode!r}")

    def _require_bm25(self) -> Retriever:
        if self._bm25_retriever is None:
            raise ValueError("BM25 retrieval is requested but no BM25 index is configured")
        return self._bm25_retriever

