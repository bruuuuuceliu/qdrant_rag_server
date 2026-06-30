"""Retrieval helper worker startup tests."""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from configs.config import AppSettings
from configs.retrieval.config import RetrievalHelperSettings
from retrieval_service.server import create_worker_server
from retrieval_service.server.worker import _build_placement_store_resolver


class RetrievalWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_worker_server_wires_broker_helper(self) -> None:
        retrieval_service = _FakeRetrievalService()
        helper_settings = RetrievalHelperSettings(
            service_name="retrieval-a",
            command_topic="retrieval.commands",
        )

        context = await create_worker_server(
            _settings(),
            helper_settings=helper_settings,
            retrieval_service=retrieval_service,
        )

        self.assertIs(context.retrieval_service, retrieval_service)
        self.assertEqual(context.helper_settings.command_topic, "retrieval.commands")
        self.assertEqual(context.helper_app.command_topic, "retrieval.commands")
        self.assertIs(context.helper_app.handler._api, context.api_app)
        health = await context.health()
        self.assertTrue(health.ready)
        self.assertEqual(health.details["command_topic"], "retrieval.commands")
        await context.shutdown()
        self.assertTrue(retrieval_service.closed)


class RetrievalWorkerRunnerTest(unittest.TestCase):
    def test_build_placement_store_resolver_uses_registry(self) -> None:
        resolver = _build_placement_store_resolver(_settings(), qdrant_store=object())

        self.assertIsNotNone(resolver)


class _FakeRetrievalService:
    def __init__(self) -> None:
        self.closed = False
        self.search = AsyncMock(return_value=None)
        self.delete_document = AsyncMock(return_value=None)
        self.get_raw_document = AsyncMock(return_value=None)

    async def shutdown(self) -> None:
        self.closed = True


def _settings() -> AppSettings:
    return AppSettings(
        response_cache_db_path=Path(":memory:"),
        grpc_port=50051,
        qdrant_url=None,
        qdrant_host="localhost",
        qdrant_port=6333,
        embedding_provider="local",
        embedding_model="fake-model",
        embedding_device="cpu",
        embedding_api_key="",
        embedding_base_url="",
        embedding_dimension=3,
        generation_enabled=False,
        bm25_encoder_model="fake-bm25",
    )


if __name__ == "__main__":
    unittest.main()
