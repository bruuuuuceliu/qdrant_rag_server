"""Broker service settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrokerSettings:
    broker_type: str = "redpanda"
    bootstrap_servers: str = "127.0.0.1:9092"
    client_id: str = "qdrant-rag-local"
    request_timeout_seconds: float = 30.0
    topic_prefix: str = ""
    topic_partitions: int = 1

    @classmethod
    def from_values(cls, values: dict[str, str]) -> BrokerSettings:
        settings = cls(
            broker_type=values.get("BROKER_TYPE", "redpanda").strip().lower(),
            bootstrap_servers=values.get("BROKER_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
            client_id=values.get("BROKER_CLIENT_ID", "qdrant-rag-local"),
            request_timeout_seconds=float(values.get("BROKER_REQUEST_TIMEOUT_SECONDS", "30")),
            topic_prefix=values.get("BROKER_TOPIC_PREFIX", ""),
            topic_partitions=int(values.get("BROKER_TOPIC_PARTITIONS", "1")),
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

    def topic(self, name: str) -> str:
        return f"{self.topic_prefix}{name}" if self.topic_prefix else name
