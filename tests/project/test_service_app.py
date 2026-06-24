"""Project service app wiring tests."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


class ProjectServiceAppTest(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_handles_reranker_without_generation_client(self) -> None:
        from project_service.server.app import AppContext

        app = AppContext(
            settings=MagicMock(),
            config_repo=MagicMock(),
            gateway=MagicMock(),
            engine=_AsyncShutdownMock(),
            project_client=MagicMock(),
            embedding_provider=_AsyncShutdownMock(),
            qdrant_store=_AsyncCloseMock(),
            bm25_index=None,
            sparse_encoder=None,
            ner_extractor=None,
            metrics=MagicMock(),
            ingest_event_broker=MagicMock(),
            reranker=_AsyncShutdownMock(),
            object_storage=MagicMock(),
            version_manager=MagicMock(),
            workflow_log_app=_AsyncShutdownMock(),
            health_checker=MagicMock(),
            openrouter_client=None,
            server=_AsyncStopMock(),
        )

        await app.shutdown()

        app.reranker.shutdown.assert_awaited_once()

    async def test_create_app_wires_workflow_log_app(self) -> None:
        from project_service.server.app import AppSettings, create_app

        with tempfile.TemporaryDirectory() as tempdir:
            settings = AppSettings(
                config_db_path=Path(tempdir) / "config.db",
                response_cache_db_path=Path(tempdir) / "response_cache.db",
                grpc_port=0,
                qdrant_url=None,
                qdrant_host="localhost",
                qdrant_port=6333,
                max_per_project=1,
                max_per_user=1,
                ingest_worker_count=1,
                embedding_provider="local",
                embedding_model="test-model",
                embedding_device="cpu",
                embedding_api_key="",
                embedding_base_url="",
                embedding_dimension=3,
                generation_enabled=False,
                workflow_log_enabled=True,
                workflow_log_db_path=Path(tempdir) / "workflow_log.db",
                workflow_log_topic="ingestion.events",
            )

            embedding_service = MagicMock()
            embedding_service.initialize = AsyncMock()
            embedding_service.shutdown = AsyncMock()

            qdrant_store = MagicMock()
            qdrant_store.close = AsyncMock()

            server = MagicMock()
            server.stop = AsyncMock()

            workflow_log_app = MagicMock()
            workflow_log_app.shutdown = AsyncMock()

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
                    "retrieval_service.embedding.EmbeddingProviderFactory.create",
                    return_value=embedding_service,
                ),
                patch(
                    "retrieval_service.services.vector_store.QdrantStore",
                    return_value=qdrant_store,
                ),
                patch(
                    "workflow_log_service.server.create_app",
                    AsyncMock(return_value=workflow_log_app),
                ) as workflow_log_create,
            ):
                app = await create_app(settings)

            workflow_log_create.assert_awaited_once()
            self.assertIs(app.workflow_log_app, workflow_log_app)

            await app.shutdown()

            workflow_log_app.shutdown.assert_awaited_once()


class _AsyncShutdownMock(MagicMock):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown = AsyncMock()


class _AsyncCloseMock(MagicMock):
    def __init__(self) -> None:
        super().__init__()
        self.close = AsyncMock()


class _AsyncStopMock(MagicMock):
    def __init__(self) -> None:
        super().__init__()
        self.stop = AsyncMock()


if __name__ == "__main__":
    unittest.main()
