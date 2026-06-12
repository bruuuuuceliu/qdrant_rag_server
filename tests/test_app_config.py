"""Application configuration tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from configs.config import get_positive_int_value, load_settings
from configs.ingestion import load_ingestion_settings
from configs.workflow_log import load_workflow_log_settings


class AppConfigTest(unittest.TestCase):
    def test_positive_int_rejects_zero_ingest_workers(self) -> None:
        with self.assertRaisesRegex(ValueError, "RAG_INGEST_WORKERS must be at least 1"):
            get_positive_int_value({"RAG_INGEST_WORKERS": "0"}, "RAG_INGEST_WORKERS", 4)

    def test_positive_int_accepts_positive_value(self) -> None:
        self.assertEqual(
            get_positive_int_value({"RAG_INGEST_WORKERS": "2"}, "RAG_INGEST_WORKERS", 4),
            2,
        )

    def test_loads_workflow_log_settings(self) -> None:
        settings = load_workflow_log_settings(
            {
                "WORKFLOW_LOG_SERVICE_ENABLED": "false",
                "WORKFLOW_LOG_SERVICE_NAME": "wf",
                "WORKFLOW_LOG_TOPIC": "ingestion.events",
                "WORKFLOW_LOG_DB_PATH": "/tmp/workflow.db",
            }
        )

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.service_name, "wf")
        self.assertEqual(settings.topic, "ingestion.events")
        self.assertEqual(settings.db_path, Path("/tmp/workflow.db"))

    def test_app_settings_include_workflow_log_settings(self) -> None:
        settings = load_settings(
            env_file=Path("/tmp/does-not-exist.env"),
            component_env_files=(),
            profile="testing",
        )

        self.assertTrue(settings.workflow_log_enabled)
        self.assertEqual(settings.workflow_log_topic, "ingestion.events")

    def test_loads_ingestion_service_settings(self) -> None:
        settings = load_ingestion_settings(
            {
                "INGESTION_SERVICE_ENABLED": "true",
                "INGESTION_SERVICE_NAME": "ingest",
                "INGESTION_REQUEST_TOPIC": "docs.in",
                "INGESTION_WORKER_COUNT": "3",
                "INGESTION_QUEUE_MAXSIZE": "50",
                "INGESTION_JOB_DB_PATH": "/tmp/jobs.db",
            }
        )

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.service_name, "ingest")
        self.assertEqual(settings.request_topic, "docs.in")
        self.assertEqual(settings.worker_count, 3)
        self.assertEqual(settings.queue_maxsize, 50)
        self.assertEqual(settings.job_db_path, Path("/tmp/jobs.db"))


if __name__ == "__main__":
    unittest.main()
