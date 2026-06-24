"""Focused coverage for examples/unites showcase helpers."""

from __future__ import annotations

from broker_service import BrokerSettings
from examples.unites.broker_roundtrip import (
    build_showcase_envelope,
    build_showcase_settings,
)
from examples.unites.sqlite_database_crud import run_sqlite_crud
from examples.unites.storage_database_crud import run_storage_crud
from shared.contracts import MessageType


def test_broker_showcase_builds_valid_settings_and_envelope() -> None:
    settings = build_showcase_settings(
        {
            "BROKER_TYPE": "redpanda",
            "BROKER_BOOTSTRAP_SERVERS": "localhost:9092",
            "BROKER_CLIENT_ID": "test-client",
            "BROKER_REQUEST_TIMEOUT_SECONDS": "5",
            "BROKER_TOPIC_PREFIX": "test.",
            "BROKER_TOPIC_PARTITIONS": "1",
        }
    )
    envelope = build_showcase_envelope()

    assert isinstance(settings, BrokerSettings)
    assert settings.topic_prefix == "test."
    assert settings.client_id == "test-client-unite-broker"
    assert envelope.message_type == MessageType.TASK_STEP
    assert envelope.data_type == "broker_showcase"
    assert envelope.payload["operation"] == "roundtrip"
    envelope.validate()


async def test_sqlite_database_crud_showcase_round_trip(tmp_path) -> None:
    summary = await run_sqlite_crud(tmp_path / "sqlite")

    assert summary.database_path == tmp_path / "sqlite" / "showcase_database.db"
    assert summary.database_path.exists()
    assert summary.created_value == "created"
    assert summary.updated_value == "updated"
    assert summary.deleted_count == 0
    assert summary.health_ok is True


async def test_storage_database_crud_showcase_round_trip(tmp_path) -> None:
    summary = await run_storage_crud(tmp_path / "storage")

    assert summary.put == {"ok": True, "key": "examples/unites/showcase.txt"}
    assert summary.get == {
        "ok": True,
        "key": "examples/unites/showcase.txt",
        "value": "created by storage_database_crud",
    }
    assert summary.delete == {"ok": True, "key": "examples/unites/showcase.txt"}
    assert summary.missing == {
        "ok": False,
        "key": "examples/unites/showcase.txt",
        "error": "not_found",
    }
