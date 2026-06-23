"""Retrieval database placement data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectPlacementScope:
    """Project-level identity used to build retrieval routing keys."""

    project_id: str
    user_id: str
    topic_id: str = ""
    doc_id: str = ""
    data_type: str = "project_document"


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    """Project routing policy for retrieval/database placement."""

    project_id: str
    routing_mode: str
    bucket_count: int = 1
    replication_factor: int = 1
    read_fanout: str = "single"
    cache_affinity: bool = True

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetrievalShard:
    """One retrieval database-serving unit."""

    shard_id: str
    cluster_id: str
    qdrant_endpoint: str
    weight: int = 100
    state: str = "active"
    qps: float = 0.0
    queue_depth: int = 0
    cpu: float = 0.0
    memory: float = 0.0


@dataclass(frozen=True, slots=True)
class PlacementRecord:
    """Persisted ownership mapping from routing key to retrieval shard."""

    placement_id: str
    placement_version: int
    routing_key: str
    primary_shard_id: str
    replica_shard_ids: tuple[str, ...]
    collection_name: str
    state: str = "active"


@dataclass(frozen=True, slots=True)
class PlacementTarget:
    """Concrete execution target for a placement-aware retrieval operation."""

    routing_key: str
    shard_id: str
    collection_name: str
    role: str = "primary"

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlacementPlan:
    """Resolved placement targets for read, write, or delete work."""

    placement_version: int
    targets: tuple[PlacementTarget, ...]
    fanout: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "placement_version": self.placement_version,
            "fanout": self.fanout,
            "targets": [target.to_mapping() for target in self.targets],
        }


@dataclass(frozen=True, slots=True)
class PlacementRebalancePlan:
    """Versioned migration plan for routing-key placement changes."""

    collection_name: str
    previous_records: tuple[PlacementRecord, ...]
    replacement_records: tuple[PlacementRecord, ...]

    @property
    def placement_version(self) -> int:
        if not self.replacement_records:
            return 0
        return max(record.placement_version for record in self.replacement_records)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "collection_name": self.collection_name,
            "placement_version": self.placement_version,
            "previous_records": [asdict(record) for record in self.previous_records],
            "replacement_records": [
                asdict(record) for record in self.replacement_records
            ],
        }
