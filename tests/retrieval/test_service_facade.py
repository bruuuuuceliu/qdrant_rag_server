"""Retrieval service facade tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from retrieval_service.retrieval import (
    DeleteDocumentRequest,
    RetrievalSearchRequest,
    RetrievalService,
)
from retrieval_service.services.bm25 import QdrantSparseBM25Index
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
                retrieval_filter=_retrieval_filter(),
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

    async def test_delete_document_uses_placement_target_store_and_collection(self) -> None:
        default_store = AsyncMock()
        primary_store = AsyncMock()
        replica_store = AsyncMock()
        resolver = _MappingResolver({"s1": primary_store, "s2": replica_store})
        bm25_index = AsyncMock()
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=default_store,
            retriever_factory=_RetrieverFactory(_Retriever()),
            bm25_index=bm25_index,
            placement_store_resolver=resolver,
        )

        await service.delete_document(
            DeleteDocumentRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                collection_name="fallback_collection",
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
        primary_store.delete_document.assert_awaited_once()
        self.assertEqual(
            primary_store.delete_document.await_args.kwargs["collection_name"],
            "placed_collection",
        )
        replica_store.delete_document.assert_awaited_once()
        self.assertEqual(
            replica_store.delete_document.await_args.kwargs["collection_name"],
            "placed_collection_replica",
        )
        default_store.delete_document.assert_not_awaited()
        self.assertEqual(bm25_index.delete_document.await_count, 2)
        self.assertEqual(
            [call.kwargs["collection_name"] for call in bm25_index.delete_document.await_args_list],
            ["placed_collection", "placed_collection_replica"],
        )

    async def test_delete_document_uses_placement_store_for_qdrant_bm25_index(self) -> None:
        default_store = AsyncMock()
        shard_store = AsyncMock()
        resolver = _Resolver(shard_store)
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=default_store,
            retriever_factory=_RetrieverFactory(_Retriever()),
            bm25_index=QdrantSparseBM25Index(store=default_store),
            placement_store_resolver=resolver,
        )

        await service.delete_document(
            DeleteDocumentRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                collection_name="fallback_collection",
                placement_plan={
                    "placement_version": 2,
                    "targets": [
                        {
                            "routing_key": "project:p1",
                            "shard_id": "s1",
                            "collection_name": "placed_collection",
                            "role": "primary",
                        }
                    ],
                },
            )
        )

        default_store.delete_document.assert_not_awaited()
        shard_store.delete_document.assert_awaited_once()

    async def test_shutdown_closes_placement_resolver(self) -> None:
        resolver = AsyncMock()
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=AsyncMock(),
            retriever_factory=_RetrieverFactory(_Retriever()),
            placement_store_resolver=resolver,
        )

        await service.shutdown()

        resolver.close.assert_awaited_once()

    async def test_search_namespaces_cache_key_with_placement_scope(self) -> None:
        cache = AsyncMock()
        cache.get.return_value = None
        retriever = _Retriever()
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=AsyncMock(),
            retriever_factory=_RetrieverFactory(retriever),
            tier1_cache=cache,
        )

        await service.search(
            RetrievalSearchRequest(
                project_id="p1",
                user_id="u1",
                query_text="hello",
                collection_name="rag_p1_v1",
                retrieval_config={"top_k": 1, "candidate_count": 3},
                retrieval_filter=_retrieval_filter(),
                cache_key="query-key",
                placement_plan={
                    "placement_version": 4,
                    "targets": [
                        {
                            "routing_key": "project:p1",
                            "shard_id": "s1",
                            "collection_name": "rag_p1_v1",
                        }
                    ],
                },
            )
        )

        cache.get.assert_awaited_once_with("p1", "v4|s1:project:p1|query-key")
        cache.set.assert_awaited_once()
        self.assertEqual(cache.set.await_args.args[1], "v4|s1:project:p1|query-key")

    async def test_search_fanout_merges_placement_targets(self) -> None:
        resolver = _SequentialResolver([_StoreHits("a", 0.3), _StoreHits("b", 0.9)])
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=AsyncMock(),
            retriever_factory=_RetrieverFactory(_Retriever()),
            placement_store_resolver=resolver,
        )

        result = await service.search(
            RetrievalSearchRequest(
                project_id="p1",
                user_id="u1",
                query_text="hello",
                collection_name="fallback",
                retrieval_config={"top_k": 2, "candidate_count": 3},
                retrieval_filter=_retrieval_filter(),
                placement_plan={
                    "placement_version": 5,
                    "fanout": True,
                    "targets": [
                        {"routing_key": "r1", "shard_id": "s1", "collection_name": "c1"},
                        {"routing_key": "r2", "shard_id": "s2", "collection_name": "c2"},
                    ],
                },
            )
        )

        self.assertEqual([chunk["text"] for chunk in result.chunks], ["b", "a"])
        self.assertEqual([store.collection_name for store in resolver.stores], ["c1", "c2"])

    async def test_search_uses_replica_when_primary_target_fails(self) -> None:
        resolver = _SequentialResolver([
            _FailingStore(),
            _StoreHits("replica", 0.8),
        ])
        service = RetrievalService(
            embedding_provider=_Embedding(),
            qdrant_store=AsyncMock(),
            retriever_factory=_RetrieverFactory(_Retriever()),
            placement_store_resolver=resolver,
        )

        result = await service.search(
            RetrievalSearchRequest(
                project_id="p1",
                user_id="u1",
                query_text="hello",
                collection_name="fallback",
                retrieval_config={"top_k": 1, "candidate_count": 3},
                retrieval_filter=_retrieval_filter(),
                placement_plan={
                    "placement_version": 5,
                    "targets": [
                        {
                            "routing_key": "r1",
                            "shard_id": "s1",
                            "collection_name": "primary_collection",
                            "role": "primary",
                        },
                        {
                            "routing_key": "r1",
                            "shard_id": "s2",
                            "collection_name": "replica_collection",
                            "role": "replica",
                        },
                    ],
                },
            )
        )

        self.assertEqual(result.chunks[0]["text"], "replica")
        self.assertEqual(resolver.stores[1].collection_name, "replica_collection")


class _Embedding:
    async def encode(self, text: str, *, task: str) -> list[float]:
        self.text = text
        self.task = task
        return [0.1, 0.2]


class _RetrievalFilter:
    project_id = "p1"
    user_id = "u1"
    allowed_user_ids = ("u1", "__shared__")
    kb_ids: tuple[str, ...] = ()
    doc_ids: tuple[str, ...] = ()


def _retrieval_filter() -> _RetrievalFilter:
    return _RetrievalFilter()


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


class _Resolver:
    def __init__(self, store):
        self.store = store
        self.target = None

    async def resolve(self, target):
        self.target = target
        return self.store


class _MappingResolver:
    def __init__(self, stores):
        self.stores = stores
        self.targets = []

    async def resolve(self, target):
        self.targets.append(target)
        return self.stores[target.shard_id]


class _SequentialResolver:
    def __init__(self, stores):
        self.stores = stores
        self.index = 0

    async def resolve(self, target):
        store = self.stores[self.index]
        store.target = target
        self.index += 1
        return store


class _StoreHits:
    def __init__(self, text: str, score: float) -> None:
        self.text = text
        self.score = score
        self.collection_name = ""

    async def search(self, *, collection_name, query_vector, query_filter, limit, vector_name=None, with_payload=True):
        self.collection_name = collection_name
        return [_Point(self.text, self.score)]


class _FailingStore:
    collection_name = ""

    async def search(self, **kwargs):
        raise RuntimeError("primary unavailable")


class _Point:
    def __init__(self, text: str, score: float) -> None:
        self.payload = {"text": text}
        self.score = score


if __name__ == "__main__":
    unittest.main()
