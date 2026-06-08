"""Phase 3 tests: embedding, Qdrant store, and RAG engine."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from retrieval_service.engine import RagEngine, SearchResult, _build_qdrant_filter
from retrieval_service.services.vector_store import (
    VECTOR_SIZE,
    _validate_upsert_input,
    make_qdrant_point_id,
)
from retrieval_service.services.embedding import (
    RemoteEmbeddingError,
    RemoteEmbeddingService,
    _parse_embedding_response,
    _redact_key,
)
from retrieval_service.gateway import IngestPlan, IngestRequest, SearchPlan
from retrieval_service.core.models import (
    BaseChunkPayload,
    BaseProjectConfig,
    BaseQueryScope,
    BaseRetrievalFilter,
    BaseChunk,
    BaseDocument,
    IngestJobStatus,
    SHARED_USER_ID,
)
from retrieval_service.adapters import ProjectAdapter


class RemoteEmbeddingServiceTest(unittest.TestCase):
    def test_parse_embedding_response(self) -> None:
        vectors = _parse_embedding_response(
            {
                "data": [
                    {"embedding": [0.1, 0.2]},
                    {"embedding": [0.3, 0.4]},
                ]
            },
            expected_count=2,
        )

        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])

    def test_parse_embedding_response_rejects_count_mismatch(self) -> None:
        with self.assertRaises(RemoteEmbeddingError):
            _parse_embedding_response({"data": []}, expected_count=1)

    def test_redacts_remote_embedding_keys(self) -> None:
        redacted = _redact_key("bad key sk-or-secret123 and sk-secret456")

        self.assertNotIn("secret123", redacted)
        self.assertNotIn("secret456", redacted)


class RemoteEmbeddingServiceAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_encode_batch_posts_openai_compatible_request(self) -> None:
        service = RemoteEmbeddingService(
            api_key="sk-or-test",
            model_name="embedding-model",
            base_url="https://example.test/embeddings",
        )
        client = MagicMock()
        response = MagicMock()
        response.is_success = True
        response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }
        client.post = AsyncMock(return_value=response)
        service._client = client

        vectors = await service.encode_batch(["a", "b"])

        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        client.post.assert_called_once()
        call = client.post.call_args
        self.assertEqual(call.args[0], "https://example.test/embeddings")
        self.assertEqual(call.kwargs["json"]["model"], "embedding-model")
        self.assertEqual(call.kwargs["json"]["input"], ["a", "b"])


class BuildQdrantFilterTest(unittest.TestCase):
    def test_single_user_no_kb_ids(self) -> None:
        rf = BaseRetrievalFilter(
            project_id="p1",
            user_id="u1",
        )
        qf = _build_qdrant_filter(rf)
        conditions = qf.must
        self.assertEqual(len(conditions), 2)
        self.assertEqual(conditions[0].key, "project_id")
        self.assertEqual(conditions[1].key, "user_id")

    def test_shared_user_match_any(self) -> None:
        rf = BaseRetrievalFilter(
            project_id="p1",
            user_id="u1",
            shared_user_id=SHARED_USER_ID,
        )
        qf = _build_qdrant_filter(rf)
        user_cond = qf.must[1]
        self.assertEqual(user_cond.key, "user_id")
        self.assertIsNotNone(user_cond.match.any)
        self.assertCountEqual(user_cond.match.any, ["u1", SHARED_USER_ID])

    def test_no_shared_user_single_match(self) -> None:
        rf = BaseRetrievalFilter(
            project_id="p1",
            user_id="u1",
            shared_user_id=None,
        )
        qf = _build_qdrant_filter(rf)
        user_cond = qf.must[1]
        self.assertEqual(user_cond.key, "user_id")
        self.assertEqual(user_cond.match.value, "u1")

    def test_single_kb_id(self) -> None:
        rf = BaseRetrievalFilter(
            project_id="p1",
            user_id="u1",
            kb_ids=("kb_a",),
        )
        qf = _build_qdrant_filter(rf)
        kb_cond = qf.must[2]
        self.assertEqual(kb_cond.key, "kb_id")
        self.assertEqual(kb_cond.match.value, "kb_a")

    def test_multiple_kb_ids_match_any(self) -> None:
        rf = BaseRetrievalFilter(
            project_id="p1",
            user_id="u1",
            kb_ids=("kb_a", "kb_b"),
        )
        qf = _build_qdrant_filter(rf)
        kb_cond = qf.must[2]
        self.assertEqual(kb_cond.key, "kb_id")
        self.assertCountEqual(kb_cond.match.any, ["kb_a", "kb_b"])

    def test_doc_ids_filter(self) -> None:
        rf = BaseRetrievalFilter(
            project_id="p1",
            user_id="u1",
            doc_ids=("d1", "d2"),
        )
        qf = _build_qdrant_filter(rf)
        doc_cond = qf.must[2]
        self.assertEqual(doc_cond.key, "doc_id")
        self.assertCountEqual(doc_cond.match.any, ["d1", "d2"])


class QdrantPointSafetyTest(unittest.TestCase):
    def test_point_id_is_stable_for_same_payload_identity(self) -> None:
        payload = BaseChunkPayload(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            chunk_id="anything",
            chunk_index=0,
            text="hello",
            data_type="document",
            chunker_version="v1",
        )

        self.assertEqual(make_qdrant_point_id(payload), make_qdrant_point_id(payload))

    def test_point_id_includes_user_scope(self) -> None:
        payload_a = BaseChunkPayload(
            project_id="p1",
            user_id="user_a",
            kb_id="kb_a",
            doc_id="shared_doc_id",
            chunk_id="shared_doc_id:0",
            chunk_index=0,
            text="hello",
        )
        payload_b = BaseChunkPayload(
            project_id="p1",
            user_id="user_b",
            kb_id="kb_a",
            doc_id="shared_doc_id",
            chunk_id="shared_doc_id:0",
            chunk_index=0,
            text="hello",
        )

        self.assertNotEqual(
            make_qdrant_point_id(payload_a),
            make_qdrant_point_id(payload_b),
        )

    def test_upsert_validation_rejects_vector_payload_count_mismatch(self) -> None:
        payload = BaseChunkPayload(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            chunk_id="d1:0",
            chunk_index=0,
            text="hello",
        )

        with self.assertRaisesRegex(ValueError, "vector count must match"):
            _validate_upsert_input([[0.1] * VECTOR_SIZE, [0.2] * VECTOR_SIZE], [payload], VECTOR_SIZE)

    def test_upsert_validation_rejects_wrong_vector_dimension(self) -> None:
        payload = BaseChunkPayload(
            project_id="p1",
            user_id="u1",
            kb_id="kb_a",
            doc_id="d1",
            chunk_id="d1:0",
            chunk_index=0,
            text="hello",
        )

        with self.assertRaisesRegex(ValueError, "expected 768"):
            _validate_upsert_input([[0.1] * 3], [payload], VECTOR_SIZE)


class RagEngineTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.embed_fn = AsyncMock()
        self.qdrant_store = AsyncMock()
        self.rerank_fn = AsyncMock()
        self.adapter = MagicMock(spec=ProjectAdapter)
        self.adapter.project_type = "test"

    def _make_search_plan(self, **kwargs: object) -> SearchPlan:
        config = BaseProjectConfig(
            project_id=kwargs.get("project_id", "p1"),
            project_type=kwargs.get("project_type", "test"),
            active_embedding_version="v1",
            embedding_model="bge-base",
            reranker_model="bge-reranker-base",
            retrieval_config=dict(kwargs.get("retrieval_config", {})),
        )
        from retrieval_service.gateway import SearchRequest

        request = SearchRequest(
            project_id=config.project_id,
            user_id="u1",
            query="test query",
        )
        scope = BaseQueryScope(
            project_id=config.project_id,
            user_id="u1",
            include_shared=True,
        )
        rf = BaseRetrievalFilter.from_scope(scope)

        return SearchPlan(
            request=request,
            adapter=self.adapter,
            config=config,
            scope=scope,
            retrieval_filter=rf,
        )

    async def test_search_returns_empty_on_no_results(self) -> None:
        self.embed_fn.return_value = [0.1] * 768
        self.qdrant_store.search.return_value = []

        engine = RagEngine(
            embed_fn=self.embed_fn,
            qdrant_store=self.qdrant_store,
        )
        plan = self._make_search_plan()
        result = await engine.search(plan)

        self.assertEqual(len(result.chunks), 0)
        self.assertFalse(result.cache_hit)

    async def test_search_sets_elapsed_ms(self) -> None:
        self.embed_fn.return_value = [0.1] * 768
        self.qdrant_store.search.return_value = []

        engine = RagEngine(
            embed_fn=self.embed_fn,
            qdrant_store=self.qdrant_store,
        )
        result = await engine.search(self._make_search_plan())

        self.assertGreaterEqual(result.elapsed_ms, 1)

    async def test_search_cache_hit_reports_elapsed_ms(self) -> None:
        tier1_cache = MagicMock()
        tier1_cache.get = AsyncMock(return_value={"chunks": [], "elapsed_ms": 0})

        engine = RagEngine(
            embed_fn=self.embed_fn,
            qdrant_store=self.qdrant_store,
            tier1_cache=tier1_cache,
        )
        result = await engine.search(self._make_search_plan())

        self.assertTrue(result.cache_hit)
        self.assertGreaterEqual(result.elapsed_ms, 1)
        self.qdrant_store.search.assert_not_called()

    async def test_search_returns_chunks_with_scores(self) -> None:
        self.embed_fn.return_value = [0.1] * 768
        self.qdrant_store.search.return_value = [
            MagicMock(
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb_a",
                    "doc_id": "d1",
                    "chunk_id": "c1",
                    "chunk_index": 0,
                    "text": "hello",
                    "metadata": {},
                },
                score=0.95,
            ),
        ]

        engine = RagEngine(
            embed_fn=self.embed_fn,
            qdrant_store=self.qdrant_store,
        )
        result = await engine.search(self._make_search_plan())

        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.chunks[0]["text"], "hello")
        self.assertAlmostEqual(result.chunks[0]["score"], 0.95)

    async def test_search_with_rerank(self) -> None:
        self.embed_fn.return_value = [0.1] * 768
        self.qdrant_store.search.return_value = [
            MagicMock(
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb_a",
                    "doc_id": "d1",
                    "chunk_id": "c1",
                    "chunk_index": 0,
                    "text": "a",
                },
                score=0.5,
            ),
            MagicMock(
                payload={
                    "project_id": "p1",
                    "user_id": "u1",
                    "kb_id": "kb_a",
                    "doc_id": "d1",
                    "chunk_id": "c2",
                    "chunk_index": 1,
                    "text": "b",
                },
                score=0.4,
            ),
        ]
        self.rerank_fn.return_value = [
            (
                {"text": "b", "chunk_id": "c2"},
                0.9,
            ),
            (
                {"text": "a", "chunk_id": "c1"},
                0.8,
            ),
        ]

        engine = RagEngine(
            embed_fn=self.embed_fn,
            qdrant_store=self.qdrant_store,
            rerank_fn=self.rerank_fn,
        )
        result = await engine.search(self._make_search_plan())

        self.assertEqual(len(result.chunks), 2)
        self.assertEqual(result.chunks[0]["text"], "b")
        self.assertEqual(result.chunks[1]["text"], "a")

    async def test_search_respects_candidate_count(self) -> None:
        self.embed_fn.return_value = [0.1] * 768
        self.qdrant_store.search.return_value = []

        engine = RagEngine(
            embed_fn=self.embed_fn,
            qdrant_store=self.qdrant_store,
        )
        plan = self._make_search_plan(
            retrieval_config={"candidate_count": 50, "top_k": 3}
        )
        await engine.search(plan)

        self.qdrant_store.search.assert_called_once()
        call_kwargs = self.qdrant_store.search.call_args.kwargs
        self.assertEqual(call_kwargs["limit"], 50)

    async def test_ingest_job_flows_through_statuses(self) -> None:
        self.adapter.parse_document = AsyncMock(
            return_value=BaseDocument(
                project_id="p1",
                user_id="u1",
                kb_id="kb_a",
                doc_id="d1",
                source_uri="s3://bucket/doc.txt",
                content_type="text/plain",
            )
        )
        self.adapter.build_chunks = AsyncMock(
            return_value=[
                BaseChunk(
                    project_id="p1",
                    user_id="u1",
                    kb_id="kb_a",
                    doc_id="d1",
                    chunk_id="c1",
                    chunk_index=0,
                    text="hello",
                )
            ]
        )
        self.adapter.build_payload = AsyncMock(
            return_value=BaseChunkPayload(
                project_id="p1",
                user_id="u1",
                kb_id="kb_a",
                doc_id="d1",
                chunk_id="c1",
                chunk_index=0,
                text="hello",
            )
        )

        embed_fn = MagicMock()
        embed_fn.encode_batch = AsyncMock(return_value=[[0.1] * 768])

        engine = RagEngine(
            embed_fn=embed_fn,
            qdrant_store=self.qdrant_store,
            ingest_worker_count=1,
        )

        plan = IngestPlan(
            request=IngestRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb_a",
                doc_id="d1",
                source_uri="s3://bucket/doc.txt",
                content_type="text/plain",
            ),
            adapter=self.adapter,
            config=BaseProjectConfig(
                project_id="p1",
                project_type="test",
                active_embedding_version="v1",
                embedding_model="bge-base",
                reranker_model="bge-reranker-base",
            ),
        )

        result = await engine.schedule_ingest(plan)
        self.assertEqual(result.job_id, result.job_id)
        self.assertEqual(result.status, IngestJobStatus.PENDING)

        # Wait for ingest to complete
        await asyncio.sleep(0.2)

        final = await engine.get_ingest_status(result.job_id)
        self.assertEqual(final.status, IngestJobStatus.COMPLETED)
        self.qdrant_store.upsert.assert_called_once()

        await engine.shutdown()

    async def test_failed_ingest_records_doc_id_and_error(self) -> None:
        self.adapter.parse_document = AsyncMock(side_effect=RuntimeError("bad input"))

        embed_fn = MagicMock()
        embed_fn.encode_batch = AsyncMock(return_value=[])

        engine = RagEngine(
            embed_fn=embed_fn,
            qdrant_store=self.qdrant_store,
            ingest_worker_count=1,
        )

        plan = IngestPlan(
            request=IngestRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb_a",
                doc_id="d1",
                source_uri="s3://bucket/doc.txt",
                content_type="text/plain",
            ),
            adapter=self.adapter,
            config=BaseProjectConfig(
                project_id="p1",
                project_type="test",
                active_embedding_version="v1",
                embedding_model="bge-base",
                reranker_model="bge-reranker-base",
            ),
        )

        result = await engine.schedule_ingest(plan)
        await asyncio.wait_for(engine._ingest_queue.join(), timeout=1)

        final = await engine.get_ingest_status(result.job_id)
        self.assertEqual(final.status, IngestJobStatus.FAILED)
        self.assertEqual(final.doc_id, "d1")
        self.assertIn("bad input", final.error)

        await engine.shutdown()


if __name__ == "__main__":
    unittest.main()
