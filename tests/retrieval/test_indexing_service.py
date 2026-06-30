"""Indexing service facade tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from retrieval_service.core.schemas import BaseChunk, BaseChunkPayload
from retrieval_service.indexing import IndexChunksRequest, IndexingService
from retrieval_service.placement import PlacementStoreResolver
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

        chunk = BaseChunk(
            document_id="d1",
            chunk_id="c1",
            chunk_index=0,
            text="hello alpha",
            metadata=_scope_metadata(),
        )
        payload = BaseChunkPayload.from_chunk(chunk)

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
        self.assertEqual(payloads[0].to_qdrant_payload()["project_id"], "p1")
        self.assertEqual(payloads[0].to_qdrant_payload()["user_id"], "u1")

    async def test_index_chunks_uses_hybrid_upsert_when_bm25_enabled(self) -> None:
        qdrant_store = AsyncMock()
        qdrant_store.upsert_hybrid_points = AsyncMock()
        service = IndexingService(
            embedding_provider=_Embedding(),
            qdrant_store=qdrant_store,
            sparse_encoder=_SparseEncoder(),
        )

        chunk = BaseChunk(
            document_id="d1",
            chunk_id="c1",
            chunk_index=0,
            text="hello alpha",
            metadata=_scope_metadata(),
        )
        payload = BaseChunkPayload.from_chunk(chunk)

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

    async def test_base_payload_metadata_scope_fields_render_for_qdrant(self) -> None:
        qdrant_store = AsyncMock()
        qdrant_store.upsert = AsyncMock()
        service = IndexingService(
            embedding_provider=_Embedding(),
            qdrant_store=qdrant_store,
        )

        chunk = BaseChunk(
            document_id="d1",
            chunk_id="c1",
            chunk_index=0,
            text="hello alpha",
            data_type="document",
            content_hash="",
            chunker_version="v1",
            metadata={},
        )
        payload = BaseChunkPayload(
            payload_id="c1",
            document_id="d1",
            chunk_id="c1",
            chunk_index=0,
            text="hello alpha",
            data_type="document",
            content_hash="",
            embedding_version="",
            chunker_version="v1",
            metadata={
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
                "visibility": "private",
            },
        )

        await service.index_chunks(
            IndexChunksRequest(
                collection_name="rag_p1_v1",
                chunks=[chunk],
                payloads=[payload],
                retrieval_config={"mode": "dense"},
            )
        )

        stored_payload = qdrant_store.upsert.await_args.kwargs["payloads"][0]
        rendered = stored_payload.to_qdrant_payload()
        self.assertEqual(rendered["project_id"], "p1")
        self.assertEqual(rendered["user_id"], "u1")
        self.assertEqual(rendered["kb_id"], "kb")
        self.assertEqual(rendered["doc_id"], "d1")
        self.assertEqual(rendered["visibility"], "private")

    async def test_index_chunks_uses_placement_target_store_and_collection(self) -> None:
        default_store = AsyncMock()
        primary_store = AsyncMock()
        replica_store = AsyncMock()
        resolver = _Resolver({"s1": primary_store, "s2": replica_store})
        service = IndexingService(
            embedding_provider=_Embedding(),
            qdrant_store=default_store,
            placement_store_resolver=resolver,
        )
        chunk = BaseChunk(
            document_id="d1",
            chunk_id="c1",
            chunk_index=0,
            text="hello alpha",
            metadata=_scope_metadata(),
        )
        payload = BaseChunkPayload.from_chunk(chunk)

        await service.index_chunks(
            IndexChunksRequest(
                collection_name="fallback_collection",
                chunks=[chunk],
                payloads=[payload],
                retrieval_config={"mode": "dense"},
                placement_plan={
                    "placement_version": 2,
                    "targets": [
                        {
                            "routing_key": "project:p1",
                            "shard_id": "s1",
                            "collection_name": "placed_collection",
                            "role": "primary",
                        },
                        {
                            "routing_key": "project:p1",
                            "shard_id": "s2",
                            "collection_name": "placed_collection_replica",
                            "role": "replica",
                        }
                    ],
                },
            )
        )

        self.assertEqual([target.shard_id for target in resolver.targets], ["s1", "s2"])
        primary_store.upsert.assert_awaited_once()
        self.assertEqual(
            primary_store.upsert.await_args.kwargs["collection_name"],
            "placed_collection",
        )
        replica_store.upsert.assert_awaited_once()
        self.assertEqual(
            replica_store.upsert.await_args.kwargs["collection_name"],
            "placed_collection_replica",
        )
        default_store.upsert.assert_not_awaited()


class _Embedding:
    async def encode_batch(self, texts, task: str):
        self.texts = list(texts)
        self.task = task
        return [[0.1, 0.2] for _ in texts]


def _scope_metadata() -> dict[str, str]:
    return {
        "project_id": "p1",
        "user_id": "u1",
        "kb_id": "kb",
        "doc_id": "d1",
    }


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


class _Resolver(PlacementStoreResolver):
    def __init__(self, stores):
        self.stores = stores
        self.targets = []

    async def resolve(self, target):
        self.targets.append(target)
        return self.stores[target.shard_id]


if __name__ == "__main__":
    unittest.main()
