"""Retriever interfaces and Qdrant-backed implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from retrieval_service.services.vector_store import QdrantStore

RetrieverSource = Literal["dense", "bm25", "metadata", "hybrid"]


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    collection_name: str
    query_text: str = ""
    query_vector: list[float] | None = None
    query_sparse_vector: Any | None = None
    retrieval_filter: Any = None
    limit: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    payload: dict[str, Any]
    score: float
    source: RetrieverSource = "dense"
    rank: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Retriever(Protocol):
    source: RetrieverSource

    async def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        ...


class QdrantVectorRetriever:
    """Retriever adapter for the existing Qdrant vector store."""

    source: RetrieverSource = "dense"

    def __init__(self, store: QdrantStore) -> None:
        self._store = store

    async def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        if query.query_vector is None:
            raise ValueError("query_vector is required for dense retrieval")
        points = await self._store.search(
            collection_name=query.collection_name,
            query_vector=query.query_vector,
            query_filter=query.retrieval_filter,
            limit=query.limit,
            vector_name=query.metadata.get("dense_vector_name"),
        )
        hits: list[RetrievalHit] = []
        for index, point in enumerate(points):
            payload = point.payload if isinstance(point.payload, dict) else {}
            hits.append(
                RetrievalHit(
                    payload=payload,
                    score=float(point.score),
                    source="dense",
                    rank=index + 1,
                )
            )
        return hits
