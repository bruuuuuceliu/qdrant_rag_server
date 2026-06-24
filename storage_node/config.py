"""Storage helper node settings."""

from __future__ import annotations

from dataclasses import dataclass

from shared.contracts import TOPICS


@dataclass(frozen=True, slots=True)
class StorageNodeSettings:
    service_name: str = "storage_node"
    command_topic: str = TOPICS.helper_storage_commands
    result_topic: str = TOPICS.helper_storage_results
    storage_root: str = "/tmp/qdrant_rag/storage_node"

    @classmethod
    def from_values(cls, values: dict[str, str]) -> StorageNodeSettings:
        return cls(
            service_name=values.get("STORAGE_NODE_SERVICE_NAME", "storage_node"),
            command_topic=values.get("STORAGE_NODE_COMMAND_TOPIC", TOPICS.helper_storage_commands),
            result_topic=values.get("STORAGE_NODE_RESULT_TOPIC", TOPICS.helper_storage_results),
            storage_root=values.get("STORAGE_NODE_ROOT", "/tmp/qdrant_rag/storage_node"),
        )

