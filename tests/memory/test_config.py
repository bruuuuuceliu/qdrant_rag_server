"""MemoryServiceSettings config tests (B3-1 signing-key guard)."""

from __future__ import annotations

import pytest

from memory_service.config import MemoryServiceSettings

_BROKER_ENV = {"MEMORY_IDENTITY_MODE": "broker", "MEMORY_INDEX_MODE": "broker", "MEMORY_SEARCH_MODE": "broker"}


def test_broker_mode_requires_signing_key() -> None:
    with pytest.raises(ValueError, match="SERVICE_AUTH_SIGNING_KEY"):
        MemoryServiceSettings.from_values(_BROKER_ENV)


def test_broker_mode_rejects_empty_signing_key() -> None:
    """B3-1: an empty-but-present SERVICE_AUTH_SIGNING_KEY must fail the guard,
    not silently yield signing_key='' (which would 401 every verification)."""
    with pytest.raises(ValueError, match="SERVICE_AUTH_SIGNING_KEY"):
        MemoryServiceSettings.from_values({**_BROKER_ENV, "SERVICE_AUTH_SIGNING_KEY": ""})


def test_broker_mode_rejects_whitespace_signing_key() -> None:
    with pytest.raises(ValueError, match="SERVICE_AUTH_SIGNING_KEY"):
        MemoryServiceSettings.from_values({**_BROKER_ENV, "SERVICE_AUTH_SIGNING_KEY": "   "})


def test_broker_mode_accepts_non_empty_signing_key() -> None:
    settings = MemoryServiceSettings.from_values(
        {**_BROKER_ENV, "SERVICE_AUTH_SIGNING_KEY": "shared-secret"}
    )
    assert settings.service_auth.signing_key == "shared-secret"


def test_fake_mode_does_not_require_signing_key() -> None:
    settings = MemoryServiceSettings.from_values(
        {
            "MEMORY_IDENTITY_MODE": "fake",
            "MEMORY_INDEX_MODE": "fake",
            "MEMORY_SEARCH_MODE": "fake",
        }
    )
    # fake mode bypasses the guard (direct construction / local dev)
    assert settings.service_auth.signing_key
