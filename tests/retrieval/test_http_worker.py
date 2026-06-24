"""Retrieval HTTP worker startup tests."""

from __future__ import annotations

from pathlib import Path
import unittest

from configs.config import AppSettings
from configs.retrieval.config import RetrievalHelperSettings, RetrievalHttpSettings
from retrieval_service.server import create_http_worker_server, create_worker_server
from retrieval_service.server.worker import _build_placement_store_resolver


class RetrievalHttpWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_worker_server_starts_http_transport_with_injected_service(self) -> None:
        retrieval_service = _FakeRetrievalService()
        http_server = _FakeHttpServer()
        seen = {}

        async def serve_http_fn(*, app, settings):
            seen["app"] = app
            seen["settings"] = settings
            return http_server

        context = await create_http_worker_server(
            _settings(),
            http_settings=RetrievalHttpSettings(
                host="127.0.0.1",
                port=18081,
                read_timeout=2.5,
            ),
            retrieval_service=retrieval_service,
            serve_http_fn=serve_http_fn,
        )

        self.assertIs(context.retrieval_service, retrieval_service)
        self.assertIs(context.http_server, http_server)
        self.assertIs(seen["app"], context.http_app)
        self.assertEqual(seen["settings"].port, 18081)
        self.assertEqual(context.http_settings.read_timeout, 2.5)

        await context.shutdown()
        self.assertTrue(http_server.closed)
        self.assertTrue(http_server.waited)
        self.assertTrue(retrieval_service.closed)

    async def test_create_worker_server_can_skip_socket_binding(self) -> None:
        retrieval_service = _FakeRetrievalService()

        context = await create_http_worker_server(
            _settings(),
            http_settings=RetrievalHttpSettings(
                host="127.0.0.1",
                port=18081,
                read_timeout=2.5,
            ),
            retrieval_service=retrieval_service,
            start_server=False,
        )

        self.assertIsNone(context.http_server)
        await context.shutdown()
        self.assertTrue(retrieval_service.closed)

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


class RetrievalHttpRunnerTest(unittest.TestCase):
    def test_build_placement_store_resolver_uses_registry(self) -> None:
        resolver = _build_placement_store_resolver(_settings(), qdrant_store=object())

        self.assertIsNotNone(resolver)

class _FakeRetrievalService:
    def __init__(self) -> None:
        self.closed = False

    async def search(self, request):
        return None

    async def delete_document(self, request):
        return None

    async def get_raw_document(self, request):
        return None

    async def shutdown(self) -> None:
        self.closed = True


class _FakeHttpServer:
    def __init__(self) -> None:
        self.closed = False
        self.waited = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited = True


def _settings() -> AppSettings:
    return AppSettings(
        config_db_path=Path(":memory:"),
        response_cache_db_path=Path(":memory:"),
        grpc_port=50051,
        qdrant_url=None,
        qdrant_host="localhost",
        qdrant_port=6333,
        max_per_project=20,
        max_per_user=5,
        ingest_worker_count=1,
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
