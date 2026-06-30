"""Standalone ingestion worker server tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from broker_service import BrokerSettings
from configs.ingestion import IngestionSettings
from ingestion_service.server.worker import create_worker_server
from shared.contracts import TOPICS


class HelperApp:
    def __init__(self, *, app, broker_settings, service_name, command_topic) -> None:
        self.app = app
        self.broker_settings = broker_settings
        self.service_name = service_name
        self.command_topic = command_topic
        self.stop = AsyncMock()


class IngestionWorkerServerTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_worker_server_wires_broker_helper_app(self) -> None:
        with TemporaryDirectory() as tempdir:
            captured = {}

            def fake_create_helper_app(*, app, broker_settings, service_name, command_topic):
                helper_app = HelperApp(
                    app=app,
                    broker_settings=broker_settings,
                    service_name=service_name,
                    command_topic=command_topic,
                )
                captured["helper_app"] = helper_app
                return helper_app

            settings = IngestionSettings(
                service_name="ingestion-a",
                command_topic="ingestion.commands",
                job_db_path=Path(tempdir) / "jobs.db",
            )
            broker_settings = BrokerSettings(client_id="ingestion-test")

            with patch("ingestion_service.server.worker.create_helper_app", fake_create_helper_app):
                context = await create_worker_server(
                    ingestion_settings=settings,
                    broker_settings=broker_settings,
                )

            self.assertIs(context.ingestion_settings, settings)
            self.assertIs(context.helper_app, captured["helper_app"])
            self.assertIs(context.helper_app.app, context.ingestion_app)
            self.assertEqual(context.helper_app.service_name, "ingestion-a")
            self.assertEqual(context.helper_app.command_topic, "ingestion.commands")
            self.assertIs(context.helper_app.broker_settings, broker_settings)
            health = await context.health()
            self.assertTrue(health.ready)
            self.assertEqual(health.details["command_topic"], "ingestion.commands")

            await context.shutdown()
            context.helper_app.stop.assert_awaited_once()

    def test_ingestion_settings_load_helper_command_topic(self) -> None:
        settings = IngestionSettings()

        self.assertEqual(settings.command_topic, TOPICS.helper_ingestion_commands)


if __name__ == "__main__":
    unittest.main()
