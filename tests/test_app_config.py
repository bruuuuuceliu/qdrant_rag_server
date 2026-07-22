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
from configs.retrieval.config import (
    load_retrieval_helper_settings,
    load_retrieval_index_worker_settings,
)
from configs.validation import validate_settings, validate_settings_or_raise


class AppConfigTest(unittest.TestCase):
    def test_positive_int_rejects_zero_retrieval_placement_bucket_count(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "RETRIEVAL_PLACEMENT_BUCKET_COUNT must be at least 1",
        ):
            get_positive_int_value(
                {"RETRIEVAL_PLACEMENT_BUCKET_COUNT": "0"},
                "RETRIEVAL_PLACEMENT_BUCKET_COUNT",
                1,
            )

    def test_positive_int_accepts_positive_value(self) -> None:
        self.assertEqual(
            get_positive_int_value(
                {"RETRIEVAL_PLACEMENT_BUCKET_COUNT": "2"},
                "RETRIEVAL_PLACEMENT_BUCKET_COUNT",
                1,
            ),
            2,
        )

    def test_load_settings_uses_local_profile_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
                profile="local",
            )

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
            settings.response_cache_db_path,
            Path("/var/lib/retrieval_service/response_cache.db"),
        )
        self.assertEqual(settings.retrieval_placement_shard_id, "retrieval-primary")

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

        self.assertEqual(settings.embedding_provider, "local")
        self.assertEqual(settings.retrieval_placement_shard_id, "local-qdrant")

    def test_promoted_production_config_defaults_to_production_profile(self) -> None:
        production_config = import_module("configs.config_production")

        with patch.dict(os.environ, {"RAG_CONFIG_PROFILE": "local"}, clear=True):
            settings = production_config.load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
            )

        self.assertEqual(
            settings.response_cache_db_path,
            Path("/var/lib/retrieval_service/response_cache.db"),
        )
        self.assertEqual(settings.retrieval_placement_shard_id, "retrieval-primary")

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

        self.assertEqual(local_settings.embedding_provider, "local")
        self.assertEqual(
            production_settings.response_cache_db_path,
            Path("/var/lib/retrieval_service/response_cache.db"),
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
                "RAG_RESPONSE_CACHE_DB_PATH": "relative.db",
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
        self.assertIn("response_cache_db_path", fields)
        self.assertIn("qdrant_url", fields)

    def test_validate_settings_rejects_unknown_embedding_provider(self) -> None:
        with patch.dict(os.environ, {"RAG_EMBEDDING_PROVIDER": "unknown"}, clear=True):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
                profile="local",
            )

        result = validate_settings(settings, profile="local")

        fields = {issue.field for issue in result.issues if issue.severity == "error"}
        self.assertFalse(result.ok)
        self.assertIn("embedding_provider", fields)

    def test_validate_settings_allows_deterministic_embedding_with_production_warning(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "RAG_EMBEDDING_PROVIDER": "deterministic",
                "RAG_EMBEDDING_API_KEY": "",
            },
            clear=True,
        ):
            settings = load_settings(
                env_file=Path("/tmp/does-not-exist.env"),
                component_env_files=(),
                profile="production",
            )

        result = validate_settings(settings, profile="production")

        warnings = {issue.field for issue in result.issues if issue.severity == "warning"}
        errors = {issue.field for issue in result.issues if issue.severity == "error"}
        self.assertTrue(result.ok)
        self.assertIn("embedding_provider", warnings)
        self.assertNotIn("embedding_api_key", errors)

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
                "INGESTION_HELPER_COMMAND_TOPIC": "ingestion.commands",
                "INGESTION_WORKER_COUNT": "3",
                "INGESTION_QUEUE_MAXSIZE": "50",
                "INGESTION_JOB_DB_PATH": "/tmp/jobs.db",
            }
        )

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.service_name, "ingest")
        self.assertEqual(settings.command_topic, "ingestion.commands")
        self.assertEqual(settings.worker_count, 3)
        self.assertEqual(settings.queue_maxsize, 50)
        self.assertEqual(settings.job_db_path, Path("/tmp/jobs.db"))

    def test_loads_manager_task_settings(self) -> None:
        settings = load_manager_settings(
            {
                "MANAGER_SERVICE_NAME": "manager-a",
                "MANAGER_TASK_INTAKE_TOPIC": "tasks.custom",
                "REDIS_TASK_STATUS_URL": "redis://redis:6379/1",
                "REDIS_TASK_STATUS_KEY_PREFIX": "rag-task:",
                "REDIS_TASK_COMPLETED_TTL_SECONDS": "60",
            }
        )

        self.assertEqual(settings.service_name, "manager-a")
        self.assertEqual(settings.task_intake_topic, "tasks.custom")
        self.assertEqual(settings.task_status_url, "redis://redis:6379/1")
        self.assertEqual(settings.task_status_key_prefix, "rag-task:")
        self.assertEqual(settings.task_completed_ttl_seconds, 60)

    def test_loads_retrieval_helper_settings(self) -> None:
        settings = load_retrieval_helper_settings(
            {
                "RETRIEVAL_HELPER_SERVICE_NAME": "retrieval-a",
                "RETRIEVAL_HELPER_COMMAND_TOPIC": "retrieval.commands",
            }
        )

        self.assertEqual(settings.service_name, "retrieval-a")
        self.assertEqual(settings.command_topic, "retrieval.commands")

    def test_loads_retrieval_index_worker_settings(self) -> None:
        settings = load_retrieval_index_worker_settings(
            {
                "RETRIEVAL_INDEX_WORKER_ENABLED": "false",
                "RETRIEVAL_INDEX_WORKER_SERVICE_NAME": "indexer",
                "RETRIEVAL_INDEX_HELPER_COMMAND_TOPIC": "index.commands",
            }
        )

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.service_name, "indexer")
        self.assertEqual(settings.command_topic, "index.commands")


if __name__ == "__main__":
    unittest.main()
