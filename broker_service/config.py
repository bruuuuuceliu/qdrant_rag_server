"""Broker service settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace

_SECURITY_PROTOCOLS = frozenset({"PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"})
_SASL_MECHANISMS = frozenset({"PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"})
_MASKED_PASSWORD = "***"


@dataclass(frozen=True, slots=True)
class BrokerSettings:
    broker_type: str = "redpanda"
    bootstrap_servers: str = "127.0.0.1:9092"
    client_id: str = "qdrant-rag-local"
    request_timeout_seconds: float = 30.0
    topic_prefix: str = ""
    topic_partitions: int = 1
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str = ""
    sasl_plain_username: str = ""
    sasl_plain_password: str = ""
    ssl_cafile: str = ""
    ssl_certfile: str = ""
    ssl_keyfile: str = ""

    @classmethod
    def from_values(cls, values: dict[str, str]) -> BrokerSettings:
        settings = cls(
            broker_type=values.get("BROKER_TYPE", "redpanda").strip().lower(),
            bootstrap_servers=values.get("BROKER_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
            client_id=values.get("BROKER_CLIENT_ID", "qdrant-rag-local"),
            request_timeout_seconds=float(values.get("BROKER_REQUEST_TIMEOUT_SECONDS", "30")),
            topic_prefix=values.get("BROKER_TOPIC_PREFIX", ""),
            topic_partitions=int(values.get("BROKER_TOPIC_PARTITIONS", "1")),
            security_protocol=values.get("BROKER_SECURITY_PROTOCOL", "PLAINTEXT").strip(),
            sasl_mechanism=values.get("BROKER_SASL_MECHANISM", "").strip(),
            sasl_plain_username=values.get("BROKER_SASL_PLAIN_USERNAME", "").strip(),
            # The SASL password is a secret: preserve it byte-for-byte (no strip).
            sasl_plain_password=values.get("BROKER_SASL_PLAIN_PASSWORD", ""),
            ssl_cafile=values.get("BROKER_SSL_CAFILE", "").strip(),
            ssl_certfile=values.get("BROKER_SSL_CERTFILE", "").strip(),
            ssl_keyfile=values.get("BROKER_SSL_KEYFILE", "").strip(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.broker_type not in {"redpanda", "kafka"}:
            raise ValueError("BROKER_TYPE must be one of: redpanda, kafka")
        if not self.bootstrap_servers.strip():
            raise ValueError("BROKER_BOOTSTRAP_SERVERS must be nonblank")
        if not self.client_id.strip():
            raise ValueError("BROKER_CLIENT_ID must be nonblank")
        if self.request_timeout_seconds <= 0:
            raise ValueError("BROKER_REQUEST_TIMEOUT_SECONDS must be > 0")
        if self.topic_partitions <= 0:
            raise ValueError("BROKER_TOPIC_PARTITIONS must be > 0")
        if any(character.isspace() for character in self.topic_prefix):
            raise ValueError("BROKER_TOPIC_PREFIX cannot contain whitespace")
        self._validate_security()

    def _validate_security(self) -> None:
        if self.security_protocol not in _SECURITY_PROTOCOLS:
            raise ValueError(
                "BROKER_SECURITY_PROTOCOL must be one of: "
                "PLAINTEXT, SSL, SASL_PLAINTEXT, SASL_SSL"
            )
        if self.security_protocol in {"SASL_PLAINTEXT", "SASL_SSL"}:
            if self.sasl_mechanism not in _SASL_MECHANISMS:
                raise ValueError(
                    "BROKER_SASL_MECHANISM must be one of: "
                    "PLAIN, SCRAM-SHA-256, SCRAM-SHA-512"
                )
            if not self.sasl_plain_username.strip():
                raise ValueError("BROKER_SASL_PLAIN_USERNAME must be nonblank for SASL")
            if not self.sasl_plain_password:
                raise ValueError("BROKER_SASL_PLAIN_PASSWORD must be nonblank for SASL")
        if self.security_protocol in {"SSL", "SASL_SSL"}:
            if not self.ssl_cafile.strip():
                raise ValueError("BROKER_SSL_CAFILE must be nonblank for SSL")
            if not os.path.isfile(self.ssl_cafile):
                raise ValueError(f"BROKER_SSL_CAFILE not found: {self.ssl_cafile}")

    def redacted(self) -> BrokerSettings:
        """Return a copy with the SASL password masked for logging."""
        if not self.sasl_plain_password:
            return self
        return replace(self, sasl_plain_password=_MASKED_PASSWORD)

    def __repr__(self) -> str:
        parts: list[str] = []
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "sasl_plain_password":
                value = _MASKED_PASSWORD if value else ""
            parts.append(f"{field.name}={value!r}")
        return f"{type(self).__name__}({', '.join(parts)})"

    def topic(self, name: str) -> str:
        return f"{self.topic_prefix}{name}" if self.topic_prefix else name
