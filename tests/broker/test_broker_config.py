"""Broker settings security validation (C5 SASL/TLS)."""

from __future__ import annotations

from pathlib import Path

import pytest

from broker_service.config import BrokerSettings


def _write_cafile(tmp_path: Path) -> Path:
    cafile = tmp_path / "ca.crt"
    cafile.write_text("dummy certificate", encoding="utf-8")
    return cafile


@pytest.mark.parametrize(
    "security_protocol",
    ("", "PLAINTEXT_TLS", "sasl_ssl", "SASL", "TLS"),
)
def test_security_protocol_rejects_unknown_values(security_protocol: str) -> None:
    with pytest.raises(ValueError, match="BROKER_SECURITY_PROTOCOL"):
        BrokerSettings(security_protocol=security_protocol).validate()


@pytest.mark.parametrize(
    "security_protocol",
    ("PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"),
)
def test_known_security_protocols_are_accepted(
    security_protocol: str, tmp_path: Path
) -> None:
    cafile = _write_cafile(tmp_path)
    kwargs: dict[str, object] = {"security_protocol": security_protocol}
    if security_protocol in {"SASL_PLAINTEXT", "SASL_SSL"}:
        kwargs.update(
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username="admin",
            sasl_plain_password="secret",
        )
    if security_protocol in {"SSL", "SASL_SSL"}:
        kwargs["ssl_cafile"] = str(cafile)
    BrokerSettings(**kwargs).validate()


def test_sasl_requires_known_mechanism(tmp_path: Path) -> None:
    cafile = _write_cafile(tmp_path)
    settings = BrokerSettings(
        security_protocol="SASL_SSL",
        sasl_mechanism="GSSAPI",
        sasl_plain_username="admin",
        sasl_plain_password="secret",
        ssl_cafile=str(cafile),
    )
    with pytest.raises(ValueError, match="BROKER_SASL_MECHANISM"):
        settings.validate()


@pytest.mark.parametrize("mechanism", ("PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"))
def test_sasl_accepts_known_mechanisms(mechanism: str) -> None:
    settings = BrokerSettings(
        security_protocol="SASL_PLAINTEXT",
        sasl_mechanism=mechanism,
        sasl_plain_username="admin",
        sasl_plain_password="secret",
    )
    settings.validate()


def test_sasl_requires_username(tmp_path: Path) -> None:
    cafile = _write_cafile(tmp_path)
    settings = BrokerSettings(
        security_protocol="SASL_SSL",
        sasl_mechanism="SCRAM-SHA-256",
        sasl_plain_username=" ",
        sasl_plain_password="secret",
        ssl_cafile=str(cafile),
    )
    with pytest.raises(ValueError, match="BROKER_SASL_PLAIN_USERNAME"):
        settings.validate()


def test_sasl_requires_password(tmp_path: Path) -> None:
    cafile = _write_cafile(tmp_path)
    settings = BrokerSettings(
        security_protocol="SASL_SSL",
        sasl_mechanism="SCRAM-SHA-256",
        sasl_plain_username="admin",
        sasl_plain_password="",
        ssl_cafile=str(cafile),
    )
    with pytest.raises(ValueError, match="BROKER_SASL_PLAIN_PASSWORD"):
        settings.validate()


def test_ssl_requires_cafile() -> None:
    with pytest.raises(ValueError, match="BROKER_SSL_CAFILE"):
        BrokerSettings(security_protocol="SSL").validate()


def test_ssl_requires_cafile_to_exist(tmp_path: Path) -> None:
    settings = BrokerSettings(
        security_protocol="SSL", ssl_cafile=str(tmp_path / "missing.crt")
    )
    with pytest.raises(ValueError, match="BROKER_SSL_CAFILE not found"):
        settings.validate()


def test_sasl_ssl_requires_cafile(tmp_path: Path) -> None:
    settings = BrokerSettings(
        security_protocol="SASL_SSL",
        sasl_mechanism="SCRAM-SHA-256",
        sasl_plain_username="admin",
        sasl_plain_password="secret",
    )
    with pytest.raises(ValueError, match="BROKER_SSL_CAFILE"):
        settings.validate()


def test_plaintext_does_not_require_security_fields() -> None:
    BrokerSettings().validate()
    BrokerSettings(security_protocol="PLAINTEXT").validate()


def test_from_values_loads_security_fields(tmp_path: Path) -> None:
    cafile = _write_cafile(tmp_path)
    settings = BrokerSettings.from_values(
        {
            "BROKER_SECURITY_PROTOCOL": "SASL_SSL",
            "BROKER_SASL_MECHANISM": "SCRAM-SHA-256",
            "BROKER_SASL_PLAIN_USERNAME": "admin",
            "BROKER_SASL_PLAIN_PASSWORD": "s3cret",
            "BROKER_SSL_CAFILE": str(cafile),
            "BROKER_SSL_CERTFILE": "/certs/client.crt",
            "BROKER_SSL_KEYFILE": "/certs/client.key",
        }
    )
    assert settings.security_protocol == "SASL_SSL"
    assert settings.sasl_mechanism == "SCRAM-SHA-256"
    assert settings.sasl_plain_username == "admin"
    assert settings.sasl_plain_password == "s3cret"
    assert settings.ssl_cafile == str(cafile)
    assert settings.ssl_certfile == "/certs/client.crt"
    assert settings.ssl_keyfile == "/certs/client.key"


def test_from_values_rejects_invalid_security(tmp_path: Path) -> None:
    cafile = _write_cafile(tmp_path)
    with pytest.raises(ValueError, match="BROKER_SECURITY_PROTOCOL"):
        BrokerSettings.from_values(
            {"BROKER_SECURITY_PROTOCOL": "GARBAGE", "BROKER_SSL_CAFILE": str(cafile)}
        )


def test_redacted_masks_password() -> None:
    settings = BrokerSettings(sasl_plain_password="hunter2")
    redacted = settings.redacted()
    assert redacted.sasl_plain_password == "***"
    # The original is unchanged; only the copy is masked.
    assert settings.sasl_plain_password == "hunter2"


def test_repr_masks_password() -> None:
    settings = BrokerSettings(sasl_plain_password="hunter2")
    assert "hunter2" not in repr(settings)
    assert "***" in repr(settings)


def test_repr_empty_password_is_not_masked() -> None:
    settings = BrokerSettings()
    assert "sasl_plain_password=''" in repr(settings)
    assert "***" not in repr(settings)


def test_redacted_no_password_returns_self() -> None:
    settings = BrokerSettings()
    assert settings.redacted() is settings
