"""Stable routing-key hashing and shard choice helpers."""

from __future__ import annotations

import hashlib

from retrieval_service.placement.models import (
    ProjectPlacementScope,
    RetrievalShard,
    RoutingPolicy,
)


ROUTING_MODES = {
    "project_single",
    "user_single",
    "topic_single",
    "user_bucketed",
    "topic_bucketed",
    "doc_bucketed",
}


def stable_hash_int(value: str) -> int:
    """Return a deterministic 64-bit integer for placement decisions."""

    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def stable_hash_float(value: str) -> float:
    """Return a deterministic float in the inclusive range [0.0, 1.0]."""

    return stable_hash_int(value) / float(2**64 - 1)


def write_routing_key(
    scope: ProjectPlacementScope,
    policy: RoutingPolicy,
) -> str:
    """Build the single routing key used by a write/delete operation."""

    _validate_policy(policy)
    _require("project_id", scope.project_id)

    if policy.routing_mode == "project_single":
        return f"project:{scope.project_id}"

    if policy.routing_mode == "user_single":
        _require("user_id", scope.user_id)
        return f"project:{scope.project_id}:user:{scope.user_id}"

    if policy.routing_mode == "topic_single":
        _require("topic_id", scope.topic_id)
        return f"project:{scope.project_id}:topic:{scope.topic_id}"

    if policy.routing_mode == "user_bucketed":
        _require("user_id", scope.user_id)
        bucket = _document_bucket(scope, policy)
        return f"project:{scope.project_id}:user:{scope.user_id}:bucket:{bucket}"

    if policy.routing_mode == "topic_bucketed":
        _require("topic_id", scope.topic_id)
        bucket = _document_bucket(scope, policy)
        return f"project:{scope.project_id}:topic:{scope.topic_id}:bucket:{bucket}"

    if policy.routing_mode == "doc_bucketed":
        bucket = _document_bucket(scope, policy)
        return f"project:{scope.project_id}:doc_bucket:{bucket}"

    raise ValueError(f"unknown routing mode: {policy.routing_mode}")


def read_routing_keys(
    scope: ProjectPlacementScope,
    policy: RoutingPolicy,
) -> tuple[str, ...]:
    """Build routing keys for a read operation, fanning out over buckets."""

    _validate_policy(policy)
    _require("project_id", scope.project_id)

    if policy.routing_mode == "user_bucketed":
        _require("user_id", scope.user_id)
        return tuple(
            f"project:{scope.project_id}:user:{scope.user_id}:bucket:{bucket}"
            for bucket in range(policy.bucket_count)
        )

    if policy.routing_mode == "topic_bucketed":
        _require("topic_id", scope.topic_id)
        return tuple(
            f"project:{scope.project_id}:topic:{scope.topic_id}:bucket:{bucket}"
            for bucket in range(policy.bucket_count)
        )

    if policy.routing_mode == "doc_bucketed":
        return tuple(
            f"project:{scope.project_id}:doc_bucket:{bucket}"
            for bucket in range(policy.bucket_count)
        )

    return (write_routing_key(scope, policy),)


def active_shards(shards: list[RetrievalShard]) -> list[RetrievalShard]:
    """Return shards eligible for new placements."""

    return [shard for shard in shards if shard.state == "active"]


def effective_weight(shard: RetrievalShard) -> float:
    """Capacity weight adjusted by current load signals."""

    base_weight = max(float(shard.weight), 0.0)
    load_penalty = (
        1.0
        + max(shard.cpu, 0.0)
        + (max(shard.memory, 0.0) * 0.5)
        + (max(float(shard.queue_depth), 0.0) / 100.0)
        + (max(shard.qps, 0.0) / 1000.0)
    )
    return base_weight / load_penalty


def rendezvous_score(routing_key: str, shard: RetrievalShard) -> float:
    """Weighted rendezvous score for a routing key/shard pair."""

    return stable_hash_float(f"{routing_key}:{shard.shard_id}") * effective_weight(
        shard
    )


def choose_shard(
    routing_key: str,
    shards: list[RetrievalShard],
) -> RetrievalShard:
    """Choose the primary shard for a new routing key."""

    candidates = active_shards(shards)
    if not candidates:
        raise ValueError("no active retrieval shards are available for placement")
    return max(candidates, key=lambda shard: rendezvous_score(routing_key, shard))


def choose_placement_shards(
    routing_key: str,
    shards: list[RetrievalShard],
    replication_factor: int = 1,
) -> tuple[RetrievalShard, tuple[RetrievalShard, ...]]:
    """Choose primary and replica shards with top-N rendezvous scores."""

    if replication_factor < 1:
        raise ValueError("replication_factor must be at least 1")
    candidates = active_shards(shards)
    if not candidates:
        raise ValueError("no active retrieval shards are available for placement")
    ranked = sorted(
        candidates,
        key=lambda shard: rendezvous_score(routing_key, shard),
        reverse=True,
    )
    selected = ranked[:replication_factor]
    return selected[0], tuple(selected[1:])


def _document_bucket(scope: ProjectPlacementScope, policy: RoutingPolicy) -> int:
    _require("doc_id", scope.doc_id)
    return stable_hash_int(scope.doc_id) % policy.bucket_count


def _validate_policy(policy: RoutingPolicy) -> None:
    if policy.routing_mode not in ROUTING_MODES:
        raise ValueError(f"unknown routing mode: {policy.routing_mode}")
    if policy.bucket_count < 1:
        raise ValueError("bucket_count must be at least 1")
    if policy.replication_factor < 1:
        raise ValueError("replication_factor must be at least 1")


def _require(name: str, value: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{name} is required for retrieval placement")

