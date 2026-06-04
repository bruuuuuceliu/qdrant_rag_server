"""Async Qdrant vector store for the RAG engine.

Manages collection lifecycle, upsert, and filtered search.  All Qdrant
calls respect ``project_id``, ``user_id``, and ``kb_id`` isolation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_server.core.models import BaseChunkPayload

logger = logging.getLogger(__name__)

VECTOR_SIZE = 768


class QdrantStore:
    """Async wrapper around Qdrant for retrieval and indexing."""

    def __init__(
        self,
        *,
        url: str | None = None,
        host: str = "localhost",
        port: int = 6333,
        **kwargs: Any,
    ) -> None:
        if url is not None:
            self._client = AsyncQdrantClient(url=url, **kwargs)
        else:
            self._client = AsyncQdrantClient(host=host, port=port, **kwargs)
        self._collection_locks: dict[str, asyncio.Lock] = {}

    async def ensure_collection_exists(
        self,
        collection_name: str,
        *,
        vector_size: int = VECTOR_SIZE,
    ) -> None:
        lock = self._collection_locks.setdefault(
            collection_name, asyncio.Lock()
        )
        async with lock:
            exists = await self._collection_exists(collection_name)
            if not exists:
                await self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info("created collection %s", collection_name)

    async def _collection_exists(self, collection_name: str) -> bool:
        try:
            await self._client.get_collection(collection_name)
            return True
        except (UnexpectedResponse, ValueError):
            return False

    async def upsert(
        self,
        collection_name: str,
        vectors: list[list[float]],
        payloads: list[BaseChunkPayload],
    ) -> None:
        await self.ensure_collection_exists(collection_name)
        points = [
            models.PointStruct(
                id=payload.chunk_id,
                vector=vector,
                payload=payload.to_qdrant_payload(),
            )
            for vector, payload in zip(vectors, payloads)
        ]
        await self._client.upsert(collection_name=collection_name, points=points)

    async def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        query_filter: models.Filter,
        limit: int = 5,
        with_payload: bool = True,
    ) -> list[models.ScoredPoint]:
        return await self._client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=with_payload,
        )

    async def delete_document(
        self,
        collection_name: str,
        doc_id: str,
    ) -> None:
        await self._client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
                )
            ),
        )

    async def delete_project(self, collection_name: str) -> None:
        await self._client.delete_collection(collection_name)
        logger.info("deleted collection %s", collection_name)

    async def collection_info(self, collection_name: str) -> dict[str, Any] | None:
        try:
            info = await self._client.get_collection(collection_name)
            return info.dict() if hasattr(info, "dict") else vars(info)
        except (UnexpectedResponse, ValueError):
            return None

    async def close(self) -> None:
        await self._client.close()
