"""Sparse and hybrid retrieval tests."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

from project_service.gateway import IngestPlan, IngestRequest, SearchPlan, SearchRequest
from project_service.rag import RagEngine
from project_service.rag.retrieval_config import parse_retrieval_settings
from project_service.schemas import (
    ProjectChunk,
    ProjectChunkPayload,
    ProjectConfig,
    ProjectDocument,
    ProjectQueryScope,
    ProjectRetrievalFilter,
)
from retrieval_service.services.bm25 import BM25Query, QdrantSparseBM25Index
from retrieval_service.services.hybrid import CandidateFusion, FusionConfig
from retrieval_service.services.retriever import RetrievalHit
from retrieval_service.services.sparse_encoder import SparseVector
from retrieval_service.services.vector_store import QdrantStore


class RetrievalConfigTest(unittest.TestCase):
    def test_parse_hybrid_settings(self) -> None:
        settings = parse_retrieval_settings(
            {
                "mode": "hybrid",
                "top_k": 3,
                "candidate_count": 10,
                "dense_weight": 0.8,
                "bm25_weight": 0.4,
                "bm25": {"index_version": "bm25_v2"},
                "ner": {
                    "enabled": True,
                    "provider": "local",
                    "model": "en_core_web_sm",
                    "boost_entities": True,
                    "entity_boost": 0.2,
                },
            }
        )

        self.assertTrue(settings.dense_enabled)
        self.assertTrue(settings.bm25_enabled)
        self.assertEqual(settings.top_k, 3)
        self.assertEqual(settings.bm25.index_version, "bm25_v2")
        self.assertTrue(settings.ner.boost_entities)

    def test_candidate_count_must_cover_top_k(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least top_k"):
            parse_retrieval_settings({"top_k": 5, "candidate_count": 2})

    def test_dense_mode_uses_named_dense_vector_only_when_bm25_config_exists(self) -> None:
        legacy_dense = parse_retrieval_settings({"mode": "dense"})
        hybrid_collection_dense = parse_retrieval_settings(
            {
                "mode": "dense",
                "bm25": {"dense_vector_name": "dense"},
            }
        )

        self.assertFalse(legacy_dense.bm25.use_named_dense_vector)
        self.assertTrue(hybrid_collection_dense.bm25.use_named_dense_vector)


class QdrantSparseBM25IndexTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_uses_qdrant_sparse_vector(self) -> None:
        store = AsyncMock()
        store.search_sparse.return_value = [
            _Point(
                payload={"chunk_id": "c1", "text": "Qdrant sparse BM25"},
                score=4.2,
            )
        ]
        index = QdrantSparseBM25Index(store=store, sparse_vector_name="bm25")

        hits = await index.search(
            query=BM25Query(
                collection_name="rag_p1_v1",
                query_text="qdrant",
                query_sparse_vector=SparseVector(indices=[1], values=[1.0]),
                retrieval_filter="scope-filter",
                limit=10,
            )
        )

        self.assertEqual([hit.payload["chunk_id"] for hit in hits], ["c1"])
        self.assertEqual(hits[0].source, "bm25")
        store.search_sparse.assert_awaited_once_with(
            collection_name="rag_p1_v1",
            sparse_vector_name="bm25",
            query_sparse_vector=SparseVector(indices=[1], values=[1.0]),
            query_filter="scope-filter",
            limit=10,
        )


class QdrantHybridCollectionSchemaTest(unittest.IsolatedAsyncioTestCase):
    async def test_existing_dense_only_collection_fails_clearly(self) -> None:
        store = object.__new__(QdrantStore)
        store._client = MagicMock()
        store._client.get_collection = AsyncMock(
            return_value=_CollectionInfo(
                {
                    "config": {
                        "params": {
                            "vectors": {
                                "size": 768,
                                "distance": "Cosine",
                            }
                        }
                    }
                }
            )
        )
        store._collection_locks = {}
        store._default_vector_size = 768

        with self.assertRaisesRegex(
            ValueError,
            "not compatible with hybrid retrieval.*named dense vector 'dense'.*sparse vector 'bm25'",
        ):
            await store.ensure_hybrid_collection_exists(
                "rag_existing_v1",
                dense_vector_name="dense",
                sparse_vector_name="bm25",
            )

        store._client.create_collection.assert_not_called()


class CandidateFusionTest(unittest.TestCase):
    def test_rrf_deduplicates_chunk_ids(self) -> None:
        fusion = CandidateFusion()
        dense_hit = RetrievalHit(
            payload={"chunk_id": "c1", "text": "dense"},
            score=0.9,
            source="dense",
            rank=1,
        )
        bm25_hit = RetrievalHit(
            payload={"chunk_id": "c1", "text": "bm25 with more text"},
            score=3.0,
            source="bm25",
            rank=1,
        )

        fused = fusion.fuse(
            [[dense_hit], [bm25_hit]],
            config=FusionConfig(dense_weight=1.0, bm25_weight=1.0),
            limit=5,
        )

        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0].source, "hybrid")
        self.assertEqual(fused[0].metadata["retrieval_sources"], ["bm25", "dense"])


class RagEngineBM25SearchTest(unittest.IsolatedAsyncioTestCase):
    async def test_dense_search_can_target_named_dense_vector(self) -> None:
        embed_provider = MagicMock()
        embed_provider.encode = AsyncMock(return_value=[0.1] * 768)
        qdrant_store = AsyncMock()
        qdrant_store.search.return_value = [
            _Point(
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "default",
                    "doc_id": "d1",
                    "chunk_id": "dense_hit",
                    "text": "Dense search inside a hybrid collection",
                    "metadata": {},
                },
                score=0.91,
            )
        ]
        engine = RagEngine(
            embedding_provider=embed_provider,
            qdrant_store=qdrant_store,
            ingest_worker_count=0,
        )
        plan = _make_plan(
            retrieval_config={
                "mode": "dense",
                "top_k": 1,
                "candidate_count": 1,
                "bm25": {"dense_vector_name": "dense"},
            },
            query="hybrid collection dense search",
        )

        result = await engine.search(plan)

        self.assertEqual(result.chunks[0]["chunk_id"], "dense_hit")
        qdrant_store.search.assert_awaited_once()
        self.assertEqual(qdrant_store.search.await_args.kwargs["vector_name"], "dense")

        await engine.shutdown()

    async def test_dense_search_legacy_config_uses_unnamed_vector(self) -> None:
        embed_provider = MagicMock()
        embed_provider.encode = AsyncMock(return_value=[0.1] * 768)
        qdrant_store = AsyncMock()
        qdrant_store.search.return_value = [
            _Point(
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "default",
                    "doc_id": "d1",
                    "chunk_id": "dense_hit",
                    "text": "Dense search inside an unnamed collection",
                    "metadata": {},
                },
                score=0.91,
            )
        ]
        engine = RagEngine(
            embedding_provider=embed_provider,
            qdrant_store=qdrant_store,
            ingest_worker_count=0,
        )
        plan = _make_plan(
            retrieval_config={
                "mode": "dense",
                "top_k": 1,
                "candidate_count": 1,
            },
            query="legacy dense collection search",
        )

        result = await engine.search(plan)

        self.assertEqual(result.chunks[0]["chunk_id"], "dense_hit")
        qdrant_store.search.assert_awaited_once()
        self.assertIsNone(qdrant_store.search.await_args.kwargs["vector_name"])

        await engine.shutdown()

    async def test_bm25_search_does_not_embed_query(self) -> None:
        embed_fn = AsyncMock()
        qdrant_store = AsyncMock()
        qdrant_store.search_sparse.return_value = [
            _Point(
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "default",
                    "doc_id": "d1",
                    "chunk_id": "c1",
                    "text": "RAG retrieves context before generation",
                    "metadata": {},
                },
                score=3.4,
            )
        ]
        sparse_encoder = _FakeSparseEncoder()
        index = QdrantSparseBM25Index(store=qdrant_store, sparse_vector_name="bm25")
        engine = RagEngine(
            embed_fn=embed_fn,
            qdrant_store=qdrant_store,
            bm25_index=index,
            sparse_encoder=sparse_encoder,
            ingest_worker_count=0,
        )
        config = ProjectConfig(
            project_id="p1",
            project_type="test",
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="none",
            retrieval_config={"mode": "bm25", "top_k": 1, "candidate_count": 5},
        )
        request = SearchRequest(
            project_id="p1",
            user_id="u1",
            query="retrieves context",
        )
        scope = ProjectQueryScope(project_id="p1", user_id="u1")
        plan = SearchPlan(
            request=request,
            adapter=MagicMock(),
            config=config,
            scope=scope,
            retrieval_filter=ProjectRetrievalFilter.from_scope(scope),
        )

        result = await engine.search(plan)

        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.chunks[0]["chunk_id"], "c1")
        embed_fn.assert_not_awaited()
        qdrant_store.search.assert_not_called()
        qdrant_store.search_sparse.assert_awaited_once()
        self.assertEqual(sparse_encoder.encoded_texts, ["retrieves context"])

        await engine.shutdown()

    async def test_hybrid_search_uses_dense_and_bm25_hits(self) -> None:
        embed_provider = MagicMock()
        embed_provider.encode = AsyncMock(return_value=[0.1] * 768)
        qdrant_store = AsyncMock()
        qdrant_store.search.return_value = [
            _Point(
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "default",
                    "doc_id": "d1",
                    "chunk_id": "dense_hit",
                    "text": "Semantic vector retrieval finds product identifiers",
                    "metadata": {},
                },
                score=0.91,
            )
        ]
        qdrant_store.search_sparse.return_value = [
            _Point(
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "default",
                    "doc_id": "d2",
                    "chunk_id": "bm25_hit",
                    "text": "Exact lexical retrieval finds SKU-42",
                    "metadata": {},
                },
                score=4.0,
            )
        ]
        sparse_encoder = _FakeSparseEncoder()
        index = QdrantSparseBM25Index(store=qdrant_store, sparse_vector_name="bm25")
        engine = RagEngine(
            embedding_provider=embed_provider,
            qdrant_store=qdrant_store,
            bm25_index=index,
            sparse_encoder=sparse_encoder,
            ingest_worker_count=0,
        )
        plan = _make_plan(
            retrieval_config={
                "mode": "hybrid",
                "top_k": 5,
                "candidate_count": 5,
            },
            query="SKU-42",
        )

        result = await engine.search(plan)

        chunk_ids = {chunk["chunk_id"] for chunk in result.chunks}
        self.assertIn("dense_hit", chunk_ids)
        self.assertIn("bm25_hit", chunk_ids)
        embed_provider.encode.assert_awaited_once()
        qdrant_store.search.assert_awaited_once()
        qdrant_store.search_sparse.assert_awaited_once()

        await engine.shutdown()

    async def test_ingest_indexes_bm25_when_hybrid_enabled(self) -> None:
        adapter = MagicMock()
        adapter.parse_document = AsyncMock(
            return_value=ProjectDocument(
                project_id="p1",
                user_id="u1",
                kb_id="default",
                doc_id="d1",
                source_uri="memory://doc",
                content_type="text/plain",
            )
        )
        adapter.build_chunks = AsyncMock(
            return_value=[
                ProjectChunk(
                    project_id="p1",
                    user_id="u1",
                    kb_id="default",
                    doc_id="d1",
                    chunk_id="d1:0",
                    chunk_index=0,
                    text="BM25 ingest stores lexical content",
                )
            ]
        )
        adapter.build_payload = AsyncMock(
            return_value=ProjectChunkPayload(
                project_id="p1",
                user_id="u1",
                kb_id="default",
                doc_id="d1",
                chunk_id="d1:0",
                chunk_index=0,
                text="BM25 ingest stores lexical content",
            )
        )

        embed_provider = MagicMock()
        embed_provider.encode_batch = AsyncMock(return_value=[[0.1] * 768])
        qdrant_store = AsyncMock()
        sparse_encoder = _FakeSparseEncoder()
        index = QdrantSparseBM25Index(store=qdrant_store, sparse_vector_name="bm25")
        engine = RagEngine(
            embedding_provider=embed_provider,
            qdrant_store=qdrant_store,
            bm25_index=index,
            sparse_encoder=sparse_encoder,
            ingest_worker_count=0,
        )
        config = ProjectConfig(
            project_id="p1",
            project_type="test",
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="none",
            retrieval_config={"mode": "hybrid", "top_k": 1, "candidate_count": 5},
        )

        await engine._run_ingest(
            "job_1",
            IngestPlan(
                request=IngestRequest(
                    project_id="p1",
                    user_id="u1",
                    kb_id="default",
                    doc_id="d1",
                    source_uri="memory://doc",
                    content_type="text/plain",
                ),
                adapter=adapter,
                config=config,
            ),
        )

        qdrant_store.upsert.assert_not_called()
        qdrant_store.upsert_hybrid_points.assert_awaited_once()
        kwargs = qdrant_store.upsert_hybrid_points.await_args.kwargs
        self.assertEqual(kwargs["sparse_vectors"], [SparseVector(indices=[1], values=[1.0])])
        self.assertEqual(kwargs["dense_vectors"], [[0.1] * 768])
        rendered = kwargs["payloads"][0].to_qdrant_payload()
        self.assertEqual(rendered["chunk_id"], "d1:0")
        self.assertEqual(rendered["text_lemmatized"], "bm25 ingest stores lexical content")

        await engine.shutdown()


def _make_plan(
    *,
    retrieval_config: dict[str, object],
    query: str,
) -> SearchPlan:
    config = ProjectConfig(
        project_id="p1",
        project_type="test",
        active_embedding_version="v1",
        embedding_model="bge-base",
        reranker_model="none",
        retrieval_config=retrieval_config,
    )
    request = SearchRequest(
        project_id="p1",
        user_id="u1",
        query=query,
    )
    scope = ProjectQueryScope(project_id="p1", user_id="u1")
    return SearchPlan(
        request=request,
        adapter=MagicMock(),
        config=config,
        scope=scope,
        retrieval_filter=ProjectRetrievalFilter.from_scope(scope),
    )


@dataclass(frozen=True, slots=True)
class _Point:
    payload: dict[str, object]
    score: float


@dataclass(frozen=True, slots=True)
class _CollectionInfo:
    data: dict[str, object]

    def dict(self) -> dict[str, object]:
        return self.data


class _FakeSparseEncoder:
    def __init__(self) -> None:
        self.encoded_texts: list[str] = []

    async def encode(self, text: str) -> SparseVector:
        self.encoded_texts.append(text)
        return SparseVector(indices=[1], values=[1.0])

    async def encode_batch(self, texts: list[str]) -> list[SparseVector]:
        self.encoded_texts.extend(texts)
        return [SparseVector(indices=[1], values=[1.0]) for _ in texts]


if __name__ == "__main__":
    unittest.main()
