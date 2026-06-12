"""Indexing service facade tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from project_service.schemas import ProjectChunk, ProjectChunkPayload
from retrieval_service.indexing import IndexChunksRequest, IndexingService
from retrieval_service.services.entities import EntityMention


class IndexingServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_index_chunks_uses_dense_upsert_and_entity_metadata(self) -> None:
        qdrant_store = AsyncMock()
        qdrant_store.upsert = AsyncMock()
        service = IndexingService(
            embedding_provider=_Embedding(),
            qdrant_store=qdrant_store,
            ner_extractor=_NER([[EntityMention(
                text="alpha",
                label="ORG",
                canonical="alpha",
                start=0,
                end=5,
            )]]),
        )

        chunk = ProjectChunk(
            project_id="p1",
            user_id="u1",
            kb_id="kb",
            doc_id="d1",
            chunk_id="c1",
            chunk_index=0,
            text="hello alpha",
        )
        payload = ProjectChunkPayload.from_chunk(chunk)

        result = await service.index_chunks(
            IndexChunksRequest(
                collection_name="rag_p1_v1",
                chunks=[chunk],
                payloads=[payload],
                retrieval_config={
                    "top_k": 1,
                    "candidate_count": 3,
                    "ner": {"enabled": True},
                },
            )
        )

        self.assertEqual(result.chunk_count, 1)
        qdrant_store.upsert.assert_awaited_once()
        vectors = qdrant_store.upsert.call_args.kwargs["vectors"]
        self.assertEqual(vectors, [[0.1, 0.2]])
        payloads = qdrant_store.upsert.call_args.kwargs["payloads"]
        self.assertEqual(payloads[0].metadata["entity_keys"], ["ORG:alpha"])

    async def test_index_chunks_uses_hybrid_upsert_when_bm25_enabled(self) -> None:
        qdrant_store = AsyncMock()
        qdrant_store.upsert_hybrid_points = AsyncMock()
        service = IndexingService(
            embedding_provider=_Embedding(),
            qdrant_store=qdrant_store,
            sparse_encoder=_SparseEncoder(),
        )

        chunk = ProjectChunk(
            project_id="p1",
            user_id="u1",
            kb_id="kb",
            doc_id="d1",
            chunk_id="c1",
            chunk_index=0,
            text="hello alpha",
        )
        payload = ProjectChunkPayload.from_chunk(chunk)

        result = await service.index_chunks(
            IndexChunksRequest(
                collection_name="rag_p1_v1",
                chunks=[chunk],
                payloads=[payload],
                retrieval_config={
                    "mode": "hybrid",
                    "top_k": 1,
                    "candidate_count": 3,
                    "bm25": {"index_version": "bm25_v1"},
                },
            )
        )

        self.assertEqual(result.chunk_count, 1)
        qdrant_store.upsert_hybrid_points.assert_awaited_once()
        kwargs = qdrant_store.upsert_hybrid_points.call_args.kwargs
        self.assertEqual(kwargs["dense_vectors"], [[0.1, 0.2]])
        self.assertEqual(kwargs["sparse_vectors"], [{"indices": [1], "values": [1.0]}])


class _Embedding:
    async def encode_batch(self, texts, task: str):
        self.texts = list(texts)
        self.task = task
        return [[0.1, 0.2] for _ in texts]


class _SparseEncoder:
    async def encode_batch(self, texts):
        self.texts = list(texts)
        return [{"indices": [1], "values": [1.0]} for _ in texts]


class _NER:
    def __init__(self, responses):
        self.responses = responses

    async def extract_batch(self, texts):
        self.texts = list(texts)
        return self.responses


if __name__ == "__main__":
    unittest.main()
