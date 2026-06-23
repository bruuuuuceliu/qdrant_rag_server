"""Application configuration tests."""

from __future__ import annotations

import os
import unittest
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from configs.config import get_positive_int_value, load_settings
from configs.ingestion import load_ingestion_settings
from configs.manager import load_manager_settings
from configs.retrieval.config import load_retrieval_index_worker_settings
from configs.validation import validate_settings, validate_settings_or_raise
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

    def test_positive_int_rejects_zero_resource_limit(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "RAG_MAX_CONCURRENT_SEARCHES must be at least 1",
        ):
            get_positive_int_value(
                {"RAG_MAX_CONCURRENT_SEARCHES": "0"},
                "RAG_MAX_CONCURRENT_SEARCHES",
                32,
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

    def test_load_settings_uses_local_profile_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
                profile="local",
            )

        self.assertEqual(settings.config_db_path, Path("/var/lib/rag/config.db"))
        self.assertEqual(settings.embedding_provider, "local")
        self.assertEqual(settings.embedding_dimension, 768)

    def test_load_settings_uses_production_profile_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
                profile="production",
            )

        self.assertEqual(
            settings.config_db_path,
            Path("/var/lib/retrieval_service/config.db"),
        )
        self.assertEqual(settings.ingest_worker_count, 4)

    def test_load_settings_can_select_profile_from_environment(self) -> None:
        with patch.dict(os.environ, {"RAG_CONFIG_PROFILE": "production"}, clear=True):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
            )

        self.assertEqual(
            settings.response_cache_db_path,
            Path("/var/lib/retrieval_service/response_cache.db"),
        )

    def test_load_settings_rejects_unknown_profile(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "unknown config profile"):
                load_settings(
                    env_file=Path("/tmp/does-not-exist.env"),
                    component_env_files=(),
                    profile="does-not-exist",
                )

    def test_profile_modules_are_active_config_compatible(self) -> None:
        local_config = import_module("configs.config_local")
        production_config = import_module("configs.config_production")

        for module in (local_config, production_config):
            self.assertTrue(hasattr(module, "AppSettings"))
            self.assertTrue(hasattr(module, "load_settings"))
            self.assertTrue(hasattr(module, "get_bool_value"))
            self.assertTrue(hasattr(module, "get_positive_int_value"))

    def test_promoted_local_config_defaults_to_local_profile(self) -> None:
        local_config = import_module("configs.config_local")

        with patch.dict(os.environ, {"RAG_CONFIG_PROFILE": "production"}, clear=True):
            settings = local_config.load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
            )

        self.assertEqual(settings.config_db_path, Path("/var/lib/rag/config.db"))
        self.assertEqual(settings.ingest_worker_count, 1)

    def test_promoted_production_config_defaults_to_production_profile(self) -> None:
        production_config = import_module("configs.config_production")

        with patch.dict(os.environ, {"RAG_CONFIG_PROFILE": "local"}, clear=True):
            settings = production_config.load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
            )

        self.assertEqual(
            settings.config_db_path,
            Path("/var/lib/retrieval_service/config.db"),
        )
        self.assertEqual(settings.ingest_worker_count, 4)

    def test_promoted_profile_app_settings_from_env_uses_promoted_default(self) -> None:
        local_config = import_module("configs.config_local")
        production_config = import_module("configs.config_production")

        with patch.dict(os.environ, {"RAG_CONFIG_PROFILE": "production"}, clear=True):
            local_settings = local_config.AppSettings.from_env(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
            )
        with patch.dict(os.environ, {"RAG_CONFIG_PROFILE": "local"}, clear=True):
            production_settings = production_config.AppSettings.from_env(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
            )

        self.assertEqual(local_settings.config_db_path, Path("/var/lib/rag/config.db"))
        self.assertEqual(
            production_settings.config_db_path,
            Path("/var/lib/retrieval_service/config.db"),
        )

    def test_env_files_and_process_env_override_profile_defaults(self) -> None:
        with TemporaryDirectory() as tempdir:
            profile_env = Path(tempdir) / "local.env"
            component_env = Path(tempdir) / "component.env"
            profile_env.write_text("RAG_GRPC_PORT=6000\n", encoding="utf-8")
            component_env.write_text("RAG_GRPC_PORT=7000\n", encoding="utf-8")
            with patch.dict(os.environ, {"RAG_GRPC_PORT": "8000"}, clear=True):
                settings = load_settings(
                    env_file=profile_env,
                    component_env_files=(component_env,),
                    profile="local",
                )

        self.assertEqual(settings.grpc_port, 8000)

    def test_validate_settings_accepts_production_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
                profile="production",
            )

        result = validate_settings(settings, profile="production")

        self.assertTrue(result.ok)

    def test_validate_settings_reports_production_errors(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RAG_EMBEDDING_PROVIDER": "openai",
                "RAG_EMBEDDING_API_KEY": "",
                "RAG_CONFIG_DB_PATH": ":memory:",
                "RAG_QDRANT_URL": "not-a-url",
            },
            clear=True,
        ):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
                profile="production",
            )

        result = validate_settings(settings, profile="production")

        fields = {issue.field for issue in result.issues if issue.severity == "error"}
        self.assertFalse(result.ok)
        self.assertIn("embedding_api_key", fields)
        self.assertIn("config_db_path", fields)
        self.assertIn("qdrant_url", fields)

    def test_validate_settings_or_raise_formats_errors(self) -> None:
        with patch.dict(os.environ, {"RAG_QDRANT_URL": "bad"}, clear=True):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
                profile="local",
            )

        with self.assertRaisesRegex(ValueError, "qdrant_url"):
            validate_settings_or_raise(settings, profile="local")

    def test_loads_ingestion_service_settings(self) -> None:
        settings = load_ingestion_settings(
            {
                "INGESTION_SERVICE_ENABLED": "true",
                "INGESTION_SERVICE_NAME": "ingest",
                "INGESTION_REQUEST_TOPIC": "docs.in",
                "INGESTION_WORKER_COUNT": "3",
                "INGESTION_QUEUE_MAXSIZE": "50",
                "INGESTION_JOB_DB_PATH": "/tmp/jobs.db",
                "INGESTION_RETRIEVAL_INDEX_ENABLED": "true",
                "INGESTION_RETRIEVAL_INDEX_TOPIC": "index.in",
                "INGESTION_RETRIEVAL_INDEX_QUEUE_BROKER": "sqlite",
                "INGESTION_RETRIEVAL_INDEX_QUEUE_DB_PATH": "/tmp/index_queue.db",
                "INGESTION_RETRIEVAL_INDEX_QUEUE_MAXSIZE": "25",
                "INGESTION_RETRIEVAL_INDEX_RESPONSE_TIMEOUT": "1.5",
            }
        )

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.service_name, "ingest")
        self.assertEqual(settings.request_topic, "docs.in")
        self.assertEqual(settings.worker_count, 3)
        self.assertEqual(settings.queue_maxsize, 50)
        self.assertEqual(settings.job_db_path, Path("/tmp/jobs.db"))
        self.assertTrue(settings.retrieval_index_enabled)
        self.assertEqual(settings.retrieval_index_topic, "index.in")
        self.assertEqual(settings.retrieval_index_queue_broker, "sqlite")
        self.assertEqual(settings.retrieval_index_queue_db_path, Path("/tmp/index_queue.db"))
        self.assertEqual(settings.retrieval_index_queue_maxsize, 25)
        self.assertEqual(settings.retrieval_index_response_timeout, 1.5)

    def test_loads_manager_retrieval_queue_settings(self) -> None:
        settings = load_manager_settings(
            {
                "MANAGER_RETRIEVAL_CLIENT_MODE": "queue",
                "MANAGER_RETRIEVAL_TOPIC": "retrieval.custom",
                "MANAGER_RETRIEVAL_RESPONSE_TIMEOUT": "2.5",
                "MANAGER_RETRIEVAL_HTTP_BASE_URL": "http://retrieval:8081",
                "MANAGER_RETRIEVAL_HTTP_TIMEOUT": "3.5",
            }
        )

        self.assertEqual(settings.retrieval_client_mode, "queue")
        self.assertEqual(settings.retrieval_topic, "retrieval.custom")
        self.assertEqual(settings.retrieval_response_timeout, 2.5)
        self.assertEqual(settings.retrieval_http_base_url, "http://retrieval:8081")
        self.assertEqual(settings.retrieval_http_timeout, 3.5)

    def test_loads_retrieval_index_worker_settings(self) -> None:
        settings = load_retrieval_index_worker_settings(
            {
                "RETRIEVAL_INDEX_WORKER_ENABLED": "false",
                "RETRIEVAL_INDEX_WORKER_SERVICE_NAME": "indexer",
                "RETRIEVAL_INDEX_REQUEST_TOPIC": "index.custom",
                "RETRIEVAL_INDEX_QUEUE_BROKER": "sqlite",
                "RETRIEVAL_INDEX_QUEUE_DB_PATH": "/tmp/index_queue.db",
                "RETRIEVAL_INDEX_QUEUE_MAXSIZE": "75",
            }
        )

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.service_name, "indexer")
        self.assertEqual(settings.request_topic, "index.custom")
        self.assertEqual(settings.queue_broker, "sqlite")
        self.assertEqual(settings.queue_db_path, Path("/tmp/index_queue.db"))
        self.assertEqual(settings.queue_maxsize, 75)


if __name__ == "__main__":
    unittest.main()
