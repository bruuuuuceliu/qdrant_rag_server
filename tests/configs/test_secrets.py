"""Secret file-injection tests (KEY_FILE resolution)."""

from __future__ import annotations

import pytest

from configs.secrets import read_secret, resolve_secret_files


def test_resolve_secret_files_reads_file_content(tmp_path: pytest.TempPathFactory) -> None:
    secret_file = tmp_path / "sasl_password"
    secret_file.write_text("hunter2\n", encoding="utf-8")
    values = {"BROKER_SASL_PLAIN_PASSWORD_FILE": str(secret_file)}
    resolved = resolve_secret_files(values)
    assert resolved["BROKER_SASL_PLAIN_PASSWORD"] == "hunter2"
    assert "BROKER_SASL_PLAIN_PASSWORD_FILE" not in resolved


def test_resolve_secret_files_keeps_missing_file_entry(tmp_path: pytest.TempPathFactory) -> None:
    missing = tmp_path / "does-not-exist"
    values = {"SERVICE_AUTH_SIGNING_KEY_FILE": str(missing)}
    resolved = resolve_secret_files(values)
    # The entry is left so the settings loader can raise a clear validation error.
    assert "SERVICE_AUTH_SIGNING_KEY_FILE" in resolved
    assert "SERVICE_AUTH_SIGNING_KEY" not in resolved


def test_resolve_secret_files_does_not_mutate_input() -> None:
    values = {"PLAIN": "1"}
    resolved = resolve_secret_files(values)
    assert values == {"PLAIN": "1"}
    assert resolved == {"PLAIN": "1"}


def test_read_secret_prefers_file_over_env(tmp_path: pytest.TempPathFactory) -> None:
    secret_file = tmp_path / "key"
    secret_file.write_text("from-file", encoding="utf-8")
    values = {"SERVICE_AUTH_SIGNING_KEY": "from-env", "SERVICE_AUTH_SIGNING_KEY_FILE": str(secret_file)}
    assert read_secret("SERVICE_AUTH_SIGNING_KEY", values) == "from-file"


def test_read_secret_falls_back_to_env() -> None:
    assert read_secret("SERVICE_AUTH_SIGNING_KEY", {"SERVICE_AUTH_SIGNING_KEY": "env-value"}) == "env-value"


def test_resolve_secret_files_strips_trailing_newline(tmp_path: pytest.TempPathFactory) -> None:
    secret_file = tmp_path / "key"
    secret_file.write_text("value-with-newline\n\n", encoding="utf-8")
    resolved = resolve_secret_files({"X_FILE": str(secret_file)})
    assert resolved["X"] == "value-with-newline"


def test_broker_settings_reads_sasl_password_from_file(tmp_path: pytest.TempPathFactory) -> None:
    from broker_service import BrokerSettings

    secret_file = tmp_path / "sasl_password"
    secret_file.write_text("secret-from-file", encoding="utf-8")
    settings = BrokerSettings.from_values(
        {
            "BROKER_SECURITY_PROTOCOL": "SASL_PLAINTEXT",
            "BROKER_SASL_MECHANISM": "SCRAM-SHA-256",
            "BROKER_SASL_PLAIN_USERNAME": "rag",
            "BROKER_SASL_PLAIN_PASSWORD_FILE": str(secret_file),
        }
    )
    assert settings.sasl_plain_password == "secret-from-file"


def test_memory_settings_reads_signing_key_from_file(tmp_path: pytest.TempPathFactory) -> None:
    from memory_service.config import MemoryServiceSettings

    secret_file = tmp_path / "signing_key"
    secret_file.write_text("shared-signing-key", encoding="utf-8")
    settings = MemoryServiceSettings.from_values(
        {
            "MEMORY_IDENTITY_MODE": "broker",
            "MEMORY_INDEX_MODE": "broker",
            "MEMORY_SEARCH_MODE": "broker",
            "SERVICE_AUTH_SIGNING_KEY_FILE": str(secret_file),
        }
    )
    assert settings.service_auth.signing_key == "shared-signing-key"
