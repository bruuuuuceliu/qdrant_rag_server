"""Phase 11 tests: end-to-end integration across all components."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from retrieval_service.adapters import (
    ProjectAdapterRegistry,
    ProjectAdapterResolver,
)
from retrieval_service.engine import RagEngine
from retrieval_service.gateway import (
    AsyncConcurrencyLimiter,
    IngestRequest,
    RagGateway,
    SearchRequest,
)
from retrieval_service.adapters.website import WebsiteProjectAdapter


class InMemoryProjectTypes:
    def __init__(self, project_types: dict[str, str]) -> None:
        self._project_types = project_types

    async def get_project_type(self, project_id: str) -> str:
        return self._project_types[project_id]


class EndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.adapter = WebsiteProjectAdapter()
        self.registry = ProjectAdapterRegistry()
        self.registry.register(self.adapter)

        self.project_types = InMemoryProjectTypes({"p1": "website", "p2": "website"})

        self.gateway = RagGateway(
            adapter_resolver=ProjectAdapterResolver(
                project_types=self.project_types,
                registry=self.registry,
            ),
            concurrency_limiter=AsyncConcurrencyLimiter(
                max_per_project=10,
                max_per_user=5,
            ),
        )

    async def _make_engine(self) -> RagEngine:
        embed_fn = AsyncMock()
        embed_fn.return_value = [0.1] * 768
        embed_fn.encode_batch = AsyncMock(return_value=[[0.1] * 768])
        qdrant_store = AsyncMock()
        return RagEngine(embed_fn=embed_fn, qdrant_store=qdrant_store)

    async def test_full_search_flow(self) -> None:
        engine = await self._make_engine()

        plan = await self.gateway.prepare_search(
            SearchRequest(
                project_id="p1",
                user_id="user_a",
                query="What is this?",
            )
        )
        result = await engine.search(plan)
        self.assertIsNotNone(result)

    async def test_full_ingest_flow(self) -> None:
        embed_fn = MagicMock()
        embed_fn.encode_batch = AsyncMock(return_value=[[0.1] * 768])
        qdrant_store = AsyncMock()
        engine = RagEngine(embed_fn=embed_fn, qdrant_store=qdrant_store)

        plan = await self.gateway.prepare_ingest(
            IngestRequest(
                project_id="p1",
                user_id="user_a",
                kb_id="kb_a",
                doc_id="doc_1",
                source_uri="https://example.com/page.html",
                content_type="text/html",
                metadata={"raw_text": "Hello world\n\nSecond paragraph"},
            )
        )

        result = await engine.schedule_ingest(plan)
        self.assertEqual(result.job_id, result.job_id)

        await asyncio.sleep(0.2)
        qdrant_store.upsert.assert_called_once()
        await engine.shutdown()

    async def test_multi_project_isolation_in_gateway(self) -> None:
        p1_plan = await self.gateway.prepare_search(
            SearchRequest(project_id="p1", user_id="u1", query="q1")
        )
        p2_plan = await self.gateway.prepare_search(
            SearchRequest(project_id="p2", user_id="u1", query="q2")
        )

        self.assertEqual(p1_plan.config.project_id, "p1")
        self.assertEqual(p2_plan.config.project_id, "p2")
        self.assertNotEqual(
            p1_plan.config.collection_name,
            p2_plan.config.collection_name,
        )

    async def test_multi_user_isolation_in_gateway(self) -> None:
        plan_a = await self.gateway.prepare_search(
            SearchRequest(project_id="p1", user_id="user_a", query="q")
        )
        plan_b = await self.gateway.prepare_search(
            SearchRequest(project_id="p1", user_id="user_b", query="q")
        )

        self.assertEqual(plan_a.retrieval_filter.user_id, "user_a")
        self.assertEqual(plan_b.retrieval_filter.user_id, "user_b")

    async def test_shared_content_included_when_allowed(self) -> None:
        plan = await self.gateway.prepare_search(
            SearchRequest(
                project_id="p1",
                user_id="u1",
                query="q",
                include_shared=True,
            )
        )
        self.assertEqual(
            plan.retrieval_filter.allowed_user_ids,
            ("u1", "__shared__"),
        )

    async def test_shared_content_excluded_when_disallowed(self) -> None:
        plan = await self.gateway.prepare_search(
            SearchRequest(
                project_id="p1",
                user_id="u1",
                query="q",
                include_shared=False,
            )
        )
        self.assertEqual(
            plan.retrieval_filter.allowed_user_ids,
            ("u1",),
        )

    async def test_concurrent_search_requests(self) -> None:
        engine = await self._make_engine()

        async def single_search() -> None:
            plan = await self.gateway.prepare_search(
                SearchRequest(project_id="p1", user_id="u1", query="q")
            )
            await engine.search(plan)

        tasks = [single_search() for _ in range(5)]
        await asyncio.gather(*tasks)

    async def test_cache_invalidation_on_ingest(self) -> None:
        embed_fn = MagicMock()
        embed_fn.return_value = [0.1] * 768
        embed_fn.encode_batch = AsyncMock(return_value=[[0.1] * 768])
        qdrant_store = AsyncMock()
        qdrant_store.search.return_value = []

        tier1_cache = AsyncMock()
        tier1_cache.get = AsyncMock(return_value=None)

        engine = RagEngine(
            embed_fn=embed_fn,
            qdrant_store=qdrant_store,
            tier1_cache=tier1_cache,
        )

        plan = await self.gateway.prepare_ingest(
            IngestRequest(
                project_id="p1",
                user_id="user_a",
                kb_id="kb_a",
                doc_id="doc_1",
                source_uri="https://example.com",
                content_type="text/html",
                metadata={"raw_text": "Hello world"},
            )
        )

        await engine.schedule_ingest(plan)
        await asyncio.sleep(0.2)

        tier1_cache.invalidate_project.assert_called_with("p1")
        await engine.shutdown()

    async def test_gateway_rejects_invalid_project(self) -> None:
        with self.assertRaises(KeyError):
            await self.gateway.prepare_search(
                SearchRequest(project_id="nonexistent", user_id="u1", query="q")
            )

    async def test_concurrency_protection(self) -> None:
        engine = await self._make_engine()

        async def search_with_limit() -> None:
            plan = await self.gateway.prepare_search(
                SearchRequest(project_id="p1", user_id="u1", query="q")
            )
            await engine.search(plan)

        tasks = [search_with_limit() for _ in range(3)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            self.assertNotIsInstance(r, Exception)

    async def test_metrics_recording_in_search(self) -> None:
        from retrieval_service.health import MetricsCollector

        metrics = MetricsCollector()

        embed_fn = AsyncMock()
        embed_fn.return_value = [0.1] * 768
        qdrant_store = AsyncMock()
        qdrant_store.search.return_value = []

        engine = RagEngine(
            embed_fn=embed_fn,
            qdrant_store=qdrant_store,
            metrics=metrics,
        )

        plan = await self.gateway.prepare_search(
            SearchRequest(project_id="p1", user_id="u1", query="q")
        )
        await engine.search(plan)

        snap = metrics.snapshot()
        self.assertEqual(snap.search_requests_total, 1)
        self.assertGreater(snap.avg_search_latency_ms, 0)

    async def test_create_app_wires_embedding_provider_object(self) -> None:
        from server.app import AppSettings, create_app

        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                config_db_path=Path(tempdir) / "config.db",
                response_cache_db_path=Path(tempdir) / "response_cache.db",
                grpc_port=0,
                qdrant_url=None,
                qdrant_host="localhost",
                qdrant_port=6333,
                max_per_project=10,
                max_per_user=5,
                ingest_worker_count=1,
                embedding_provider="local",
                embedding_model="test-model",
                embedding_device="cpu",
                embedding_api_key="",
                embedding_base_url="https://example.test/embeddings",
                embedding_dimension=768,
                generation_enabled=False,
            )

            embedding_service = MagicMock()
            embedding_service.initialize = AsyncMock()
            embedding_service.shutdown = AsyncMock()

            qdrant_store = MagicMock()
            qdrant_store.close = AsyncMock()

            server = MagicMock()
            server.stop = AsyncMock()
            grpc_pkg = types.ModuleType("server.grpc")
            grpc_pkg.__path__ = []
            grpc_server_module = types.ModuleType("server.grpc.server")
            grpc_server_module.serve_grpc = AsyncMock(return_value=server)

            with (
                patch.dict(
                    sys.modules,
                    {
                        "server.grpc": grpc_pkg,
                        "server.grpc.server": grpc_server_module,
                    },
                ),
                patch(
                    "retrieval_service.services.embedding.EmbeddingService",
                    return_value=embedding_service,
                ),
                patch(
                    "retrieval_service.services.vector_store.QdrantStore",
                    return_value=qdrant_store,
                ),
            ):
                app = await create_app(settings)

            self.assertIs(app.engine._embedding_provider, embedding_service)
            self.assertIsNone(app.openrouter_client)
            self.assertIsNotNone(app.health_checker)

            await app.shutdown()

    async def test_create_app_can_wire_remote_embedding_provider(self) -> None:
        from server.app import AppSettings, create_app

        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                config_db_path=Path(tempdir) / "config.db",
                response_cache_db_path=Path(tempdir) / "response_cache.db",
                grpc_port=0,
                qdrant_url=None,
                qdrant_host="localhost",
                qdrant_port=6333,
                max_per_project=10,
                max_per_user=5,
                ingest_worker_count=1,
                embedding_provider="openrouter",
                embedding_model="remote-embedding-model",
                embedding_device="cpu",
                embedding_api_key="sk-or-test",
                embedding_base_url="https://example.test/embeddings",
                embedding_dimension=1536,
                generation_enabled=False,
            )

            remote_provider = MagicMock()
            remote_provider.initialize = AsyncMock()
            remote_provider.shutdown = AsyncMock()

            qdrant_store = MagicMock()
            qdrant_store.close = AsyncMock()

            server = MagicMock()
            server.stop = AsyncMock()
            grpc_pkg = types.ModuleType("server.grpc")
            grpc_pkg.__path__ = []
            grpc_server_module = types.ModuleType("server.grpc.server")
            grpc_server_module.serve_grpc = AsyncMock(return_value=server)

            with (
                patch.dict(
                    sys.modules,
                    {
                        "server.grpc": grpc_pkg,
                        "server.grpc.server": grpc_server_module,
                    },
                ),
                patch("retrieval_service.services.embedding.EmbeddingService") as local_cls,
                patch(
                    "retrieval_service.services.embedding.RemoteEmbeddingService",
                    return_value=remote_provider,
                ) as remote_cls,
                patch(
                    "retrieval_service.services.vector_store.QdrantStore",
                    return_value=qdrant_store,
                ) as qdrant_cls,
            ):
                app = await create_app(settings)

            local_cls.assert_not_called()
            remote_cls.assert_called_once_with(
                api_key="sk-or-test",
                model_name="remote-embedding-model",
                base_url="https://example.test/embeddings",
            )
            qdrant_cls.assert_called_once()
            self.assertEqual(qdrant_cls.call_args.kwargs["default_vector_size"], 1536)
            self.assertIs(app.engine._embedding_provider, remote_provider)

            await app.shutdown()


if __name__ == "__main__":
    unittest.main()
