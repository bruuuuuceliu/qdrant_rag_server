"""Retrieval placement resolver."""

from __future__ import annotations

from uuid import uuid4

from retrieval_service.placement.hashing import (
    choose_placement_shards,
    read_routing_keys,
    write_routing_key,
)
from retrieval_service.placement.models import (
    PlacementRebalancePlan,
    PlacementPlan,
    PlacementRecord,
    PlacementTarget,
    ProjectPlacementScope,
    RoutingPolicy,
)
from retrieval_service.placement.repository import (
    PlacementRepository,
    RetrievalShardRepository,
    RoutingPolicyRepository,
)


class PlacementResolver:
    """Resolve read/write scopes to persisted retrieval shard placement plans."""

    def __init__(
        self,
        *,
        shard_repository: RetrievalShardRepository,
        placement_repository: PlacementRepository,
        policy_repository: RoutingPolicyRepository | None = None,
        default_policy: RoutingPolicy | None = None,
    ) -> None:
        self._shards = shard_repository
        self._placements = placement_repository
        self._policies = policy_repository
        self._default_policy = default_policy

    def get_policy(self, project_id: str) -> RoutingPolicy:
        policy = None
        if self._policies is not None:
            policy = self._policies.get_policy(project_id)
        policy = policy or self._default_policy
        if policy is None:
            return RoutingPolicy(project_id=project_id, routing_mode="project_single")
        if policy.project_id in (project_id, "*"):
            return RoutingPolicy(
                project_id=project_id,
                routing_mode=policy.routing_mode,
                bucket_count=policy.bucket_count,
                replication_factor=policy.replication_factor,
                read_fanout=policy.read_fanout,
                cache_affinity=policy.cache_affinity,
            )
        return policy

    def save_policy(self, policy: RoutingPolicy) -> None:
        if self._policies is None:
            raise RuntimeError("routing policy repository is not configured")
        self._policies.save_policy(policy)

    def resolve_project_write(
        self,
        *,
        scope: ProjectPlacementScope,
        collection_name: str,
    ) -> PlacementPlan:
        return self.resolve_write(
            scope=scope,
            policy=self.get_policy(scope.project_id),
            collection_name=collection_name,
        )

    def resolve_project_read(
        self,
        *,
        scope: ProjectPlacementScope,
        collection_name: str,
    ) -> PlacementPlan:
        return self.resolve_read(
            scope=scope,
            policy=self.get_policy(scope.project_id),
            collection_name=collection_name,
        )

    def resolve_write(
        self,
        *,
        scope: ProjectPlacementScope,
        policy: RoutingPolicy,
        collection_name: str,
    ) -> PlacementPlan:
        """Resolve a write/delete request to one routing key placement."""

        routing_key = write_routing_key(scope, policy)
        record = self.get_or_create_placement(
            routing_key=routing_key,
            collection_name=collection_name,
            replication_factor=policy.replication_factor,
        )
        return PlacementPlan(
            placement_version=record.placement_version,
            targets=_targets_from_record(record),
            fanout=False,
        )

    def resolve_read(
        self,
        *,
        scope: ProjectPlacementScope,
        policy: RoutingPolicy,
        collection_name: str,
    ) -> PlacementPlan:
        """Resolve a read request, fanning out across bucketed routing keys."""

        routing_keys = read_routing_keys(scope, policy)
        records = tuple(
            self.get_or_create_placement(
                routing_key=routing_key,
                collection_name=collection_name,
                replication_factor=policy.replication_factor,
            )
            for routing_key in routing_keys
        )
        placement_version = max(record.placement_version for record in records)
        targets: list[PlacementTarget] = []
        for record in records:
            targets.extend(_targets_from_record(record))
        return PlacementPlan(
            placement_version=placement_version,
            targets=tuple(targets),
            fanout=len(routing_keys) > 1,
        )

    def get_or_create_placement(
        self,
        *,
        routing_key: str,
        collection_name: str,
        replication_factor: int = 1,
    ) -> PlacementRecord:
        """Return the active stored placement or assign a new one."""

        existing = self._placements.get_active(routing_key, collection_name)
        if existing is not None:
            return existing

        primary, replicas = choose_placement_shards(
            routing_key,
            self._shards.list_active(),
            replication_factor=replication_factor,
        )
        record = PlacementRecord(
            placement_id=f"plc-{uuid4().hex}",
            placement_version=self._placements.next_version(),
            routing_key=routing_key,
            primary_shard_id=primary.shard_id,
            replica_shard_ids=tuple(shard.shard_id for shard in replicas),
            collection_name=collection_name,
            state="active",
        )
        self._placements.save(record)
        return record

    def begin_rebalance(
        self,
        *,
        collection_name: str,
        target_state: str = "moving",
    ) -> PlacementRebalancePlan:
        """Create replacement records for active placements without activating them."""

        previous = tuple(
            record
            for record in self._placements.list_by_collection(collection_name)
            if record.state == "active"
        )
        replacements: list[PlacementRecord] = []
        for record in previous:
            primary, replicas = choose_placement_shards(
                record.routing_key,
                self._shards.list_active(),
                replication_factor=1 + len(record.replica_shard_ids),
            )
            replacement = PlacementRecord(
                placement_id=f"plc-{uuid4().hex}",
                placement_version=self._placements.next_version(),
                routing_key=record.routing_key,
                primary_shard_id=primary.shard_id,
                replica_shard_ids=tuple(shard.shard_id for shard in replicas),
                collection_name=record.collection_name,
                state=target_state,
            )
            self._placements.save(replacement)
            self._placements.mark_state(record.placement_id, "moving")
            replacements.append(replacement)
        return PlacementRebalancePlan(
            collection_name=collection_name,
            previous_records=previous,
            replacement_records=tuple(replacements),
        )

    def activate_rebalance(self, plan: PlacementRebalancePlan) -> None:
        for record in plan.previous_records:
            self._placements.mark_state(record.placement_id, "stale")
        for record in plan.replacement_records:
            self._placements.mark_state(record.placement_id, "active")


def _targets_from_record(record: PlacementRecord) -> tuple[PlacementTarget, ...]:
    targets = [
        PlacementTarget(
            routing_key=record.routing_key,
            shard_id=record.primary_shard_id,
            collection_name=record.collection_name,
            role="primary",
        )
    ]
    targets.extend(
        PlacementTarget(
            routing_key=record.routing_key,
            shard_id=shard_id,
            collection_name=record.collection_name,
            role="replica",
        )
        for shard_id in record.replica_shard_ids
    )
    return tuple(targets)
