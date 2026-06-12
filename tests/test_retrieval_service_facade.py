"""Retrieval service facade tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from project_service.schemas import ProjectRetrievalFilter
from retrieval_service.retrieval import (
    DeleteDocumentRequest,
    RetrievalSearchRequest,
    RetrievalService,
)
from retrieval_service.services.retriever import RetrievalHit


class RetrievalServiceFacadeTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_builds_query_and_returns_scored_chunks(self) -> None:
        embedding = _Embedding()
        retriever = _Retriever()
        service = RetrievalService(
            embedding_provider=embedding,
            qdrant_store=AsyncMock(),
            retriever_factory=_RetrieverFactory(retriever),
        )

        result = await service.search(
            RetrievalSearchRequest(
                project_id="p1",
                user_id="u1",
                query_text="hello",
                collection_name="rag_p1_v1",
                retrieval_config={"top_k": 1, "candidate_count": 3},
                retrieval_filter=ProjectRetrievalFilter(project_id="p1", user_id="u1"),
            )
        )

        self.assertEqual(result.chunks, [{"text": "answer", "score": 0.7}])
        self.assertEqual(retriever.query.collection_name, "rag_p1_v1")
        self.assertEqual(retriever.query.query_vector, [0.1, 0.2])
        self.assertEqual(retriever.query.limit, 3)
        self.assertEqual(
            retriever.query.metadata["filter_fields"],
            {"project_id": "p1", "user_id": ("u1", "__shared__")},
        )

    async def test_search_requires_retrieval_filter(self) -> None:
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=AsyncMock(),
            retriever_factory=_RetrieverFactory(_Retriever()),
        )

        with self.assertRaisesRegex(ValueError, "retrieval_filter is required"):
            await service.search(
                RetrievalSearchRequest(
                    project_id="p1",
                    user_id="u1",
                    query_text="hello",
                    collection_name="rag_p1_v1",
                    retrieval_config={"top_k": 1, "candidate_count": 3},
                )
            )

    async def test_delete_document_deletes_qdrant_raw_storage_and_caches(self) -> None:
        qdrant_store = AsyncMock()
        object_storage = AsyncMock()
        tier1_cache = AsyncMock()
        tier2_cache = AsyncMock()
        bm25_index = AsyncMock()
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=qdrant_store,
            retriever_factory=_RetrieverFactory(_Retriever()),
            object_storage=object_storage,
            tier1_cache=tier1_cache,
            tier2_cache=tier2_cache,
            bm25_index=bm25_index,
        )

        await service.delete_document(
            DeleteDocumentRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                collection_name="rag_p1_v1",
            )
        )

        qdrant_store.delete_document.assert_awaited_once_with(
            collection_name="rag_p1_v1",
            project_id="p1",
            user_id="u1",
            kb_id="kb",
            doc_id="d1",
        )
        object_storage.delete.assert_awaited_once()
        bm25_index.delete_document.assert_awaited_once_with(
            collection_name="rag_p1_v1",
            filter_fields={
                "project_id": "p1",
                "user_id": "u1",
                "kb_id": "kb",
                "doc_id": "d1",
            },
        )
        tier1_cache.invalidate_project.assert_awaited_once_with("p1")
        tier2_cache.invalidate_user.assert_awaited_once_with("p1", "u1")

    async def test_delete_document_invalidates_caches_when_raw_delete_fails(self) -> None:
        qdrant_store = AsyncMock()
        object_storage = AsyncMock()
        object_storage.delete.side_effect = RuntimeError("storage unavailable")
        tier1_cache = AsyncMock()
        tier2_cache = AsyncMock()
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=qdrant_store,
            retriever_factory=_RetrieverFactory(_Retriever()),
            object_storage=object_storage,
            tier1_cache=tier1_cache,
            tier2_cache=tier2_cache,
        )

        with self.assertRaises(RuntimeError):
            await service.delete_document(
                DeleteDocumentRequest(
                    project_id="p1",
                    user_id="u1",
                    kb_id="kb",
                    doc_id="d1",
                    collection_name="rag_p1_v1",
                )
            )

        qdrant_store.delete_document.assert_awaited_once()
        tier1_cache.invalidate_project.assert_awaited_once_with("p1")
        tier2_cache.invalidate_user.assert_awaited_once_with("p1", "u1")


class _Embedding:
    async def encode(self, text: str, *, task: str) -> list[float]:
        self.text = text
        self.task = task
        return [0.1, 0.2]


class _Retriever:
    source = "dense"

    async def search(self, query):
        self.query = query
        return [RetrievalHit(payload={"text": "answer"}, score=0.7)]


class _RetrieverFactory:
    def __init__(self, retriever: _Retriever) -> None:
        self.retriever = retriever

    def build(self, *, settings):
        self.settings = settings
        return self.retriever


if __name__ == "__main__":
    unittest.main()
