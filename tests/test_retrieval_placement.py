"""Retrieval/database placement tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from retrieval_service.placement import (
    InMemoryPlacementRepository,
    InMemoryRoutingPolicyRepository,
    InMemoryRetrievalShardRepository,
    PlacementResolver,
    ProjectPlacementScope,
    RetrievalShard,
    RoutingPolicy,
    SQLitePlacementRegistry,
    choose_placement_shards,
    choose_shard,
    read_routing_keys,
    stable_hash_int,
    write_routing_key,
)


class RetrievalPlacementTest(unittest.TestCase):
    def test_stable_hash_is_deterministic(self) -> None:
        self.assertEqual(stable_hash_int("project:p1"), stable_hash_int("project:p1"))
        self.assertNotEqual(stable_hash_int("project:p1"), stable_hash_int("project:p2"))

    def test_choose_shard_is_deterministic(self) -> None:
        shards = _shards(3)

        first = choose_shard("project:p1:topic:t1", shards)
        second = choose_shard("project:p1:topic:t1", list(reversed(shards)))

        self.assertEqual(first.shard_id, second.shard_id)

    def test_higher_weight_receives_more_new_assignments(self) -> None:
        low = RetrievalShard(
            shard_id="low",
            cluster_id="cluster",
            qdrant_endpoint="http://low:6333",
            weight=50,
        )
        high = RetrievalShard(
            shard_id="high",
            cluster_id="cluster",
            qdrant_endpoint="http://high:6333",
            weight=500,
        )

        high_count = sum(
            1
            for index in range(1000)
            if choose_shard(f"project:p1:topic:{index}", [low, high]).shard_id
            == "high"
        )

        self.assertGreater(high_count, 850)

    def test_existing_placement_is_reused_after_load_changes(self) -> None:
        shard_repo = InMemoryRetrievalShardRepository(_shards(2))
        placement_repo = InMemoryPlacementRepository()
        resolver = PlacementResolver(
            shard_repository=shard_repo,
            placement_repository=placement_repo,
        )
        scope = ProjectPlacementScope(project_id="p1", user_id="u1", topic_id="t1")
        policy = RoutingPolicy(project_id="p1", routing_mode="topic_single")

        first = resolver.resolve_write(
            scope=scope,
            policy=policy,
            collection_name="rag_p1_v1",
        )
        original_shard_id = first.targets[0].shard_id
        shard_repo.upsert(
            RetrievalShard(
                shard_id=original_shard_id,
                cluster_id="cluster",
                qdrant_endpoint=f"http://{original_shard_id}:6333",
                weight=1,
                qps=100000,
                queue_depth=100000,
                cpu=100,
                memory=100,
            )
        )

        second = resolver.resolve_write(
            scope=scope,
            policy=policy,
            collection_name="rag_p1_v1",
        )

        self.assertEqual(second.targets[0].shard_id, original_shard_id)
        self.assertEqual(second.placement_version, first.placement_version)

    def test_bucketed_routing_keys_for_write_and_read(self) -> None:
        scope = ProjectPlacementScope(
            project_id="p1",
            user_id="u1",
            topic_id="rentals",
            doc_id="doc-9",
        )
        policy = RoutingPolicy(
            project_id="p1",
            routing_mode="topic_bucketed",
            bucket_count=4,
        )
        expected_bucket = stable_hash_int("doc-9") % 4

        self.assertEqual(
            write_routing_key(scope, policy),
            f"project:p1:topic:rentals:bucket:{expected_bucket}",
        )
        self.assertEqual(
            read_routing_keys(scope, policy),
            (
                "project:p1:topic:rentals:bucket:0",
                "project:p1:topic:rentals:bucket:1",
                "project:p1:topic:rentals:bucket:2",
                "project:p1:topic:rentals:bucket:3",
            ),
        )

    def test_replica_selection_returns_distinct_active_shards(self) -> None:
        primary, replicas = choose_placement_shards(
            "project:p1:topic:t1",
            _shards(4) + [_down_shard()],
            replication_factor=3,
        )
        selected_ids = [primary.shard_id, *(replica.shard_id for replica in replicas)]

        self.assertEqual(len(selected_ids), 3)
        self.assertEqual(len(set(selected_ids)), 3)
        self.assertNotIn("down", selected_ids)

    def test_no_active_shards_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "no active retrieval shards"):
            choose_shard("project:p1", [_down_shard()])

    def test_sqlite_registry_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = SQLitePlacementRegistry(Path(temp_dir) / "placement.sqlite")
            registry.initialize()
            registry.upsert(_shards(1)[0])
            resolver = PlacementResolver(
                shard_repository=registry,
                placement_repository=registry,
            )

            plan = resolver.resolve_write(
                scope=ProjectPlacementScope(
                    project_id="p1",
                    user_id="u1",
                    topic_id="t1",
                ),
                policy=RoutingPolicy(project_id="p1", routing_mode="topic_single"),
                collection_name="rag_p1_v1",
            )
            active = registry.get_active(
                "project:p1:topic:t1",
                "rag_p1_v1",
            )

            self.assertIsNotNone(active)
            self.assertEqual(registry.get("shard-0").qdrant_endpoint, "http://shard-0:6333")
            self.assertEqual(active.primary_shard_id, "shard-0")
            self.assertEqual(plan.to_mapping()["targets"][0]["shard_id"], "shard-0")

    def test_routing_policy_repository_falls_back_to_default_policy(self) -> None:
        policies = InMemoryRoutingPolicyRepository(
            [
                RoutingPolicy(
                    project_id="*",
                    routing_mode="topic_bucketed",
                    bucket_count=3,
                    replication_factor=2,
                )
            ]
        )
        resolver = PlacementResolver(
            shard_repository=InMemoryRetrievalShardRepository(_shards(3)),
            placement_repository=InMemoryPlacementRepository(),
            policy_repository=policies,
        )

        policy = resolver.get_policy("p1")

        self.assertEqual(policy.project_id, "p1")
        self.assertEqual(policy.routing_mode, "topic_bucketed")
        self.assertEqual(policy.bucket_count, 3)
        self.assertEqual(policy.replication_factor, 2)

    def test_sqlite_registry_persists_routing_policies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = SQLitePlacementRegistry(Path(temp_dir) / "placement.sqlite")
            registry.initialize()
            registry.save_policy(
                RoutingPolicy(
                    project_id="p1",
                    routing_mode="doc_bucketed",
                    bucket_count=8,
                    replication_factor=2,
                    read_fanout="all",
                    cache_affinity=False,
                )
            )

            policy = registry.get_policy("p1")

            self.assertIsNotNone(policy)
            self.assertEqual(policy.routing_mode, "doc_bucketed")
            self.assertEqual(policy.bucket_count, 8)
            self.assertEqual(policy.replication_factor, 2)
            self.assertEqual(policy.read_fanout, "all")
            self.assertFalse(policy.cache_affinity)

    def test_rebalance_creates_moving_replacements_then_activates(self) -> None:
        placement_repo = InMemoryPlacementRepository()
        resolver = PlacementResolver(
            shard_repository=InMemoryRetrievalShardRepository(_shards(3)),
            placement_repository=placement_repo,
        )
        scope = ProjectPlacementScope(project_id="p1", user_id="u1", topic_id="t1")
        resolver.resolve_write(
            scope=scope,
            policy=RoutingPolicy(project_id="p1", routing_mode="topic_single"),
            collection_name="rag_p1_v1",
        )

        plan = resolver.begin_rebalance(collection_name="rag_p1_v1")

        self.assertEqual(len(plan.previous_records), 1)
        self.assertEqual(len(plan.replacement_records), 1)
        self.assertEqual(plan.previous_records[0].state, "active")
        stored = placement_repo.list_by_collection("rag_p1_v1")
        self.assertEqual([record.state for record in stored], ["moving", "moving"])

        resolver.activate_rebalance(plan)

        active = placement_repo.get_active("project:p1:topic:t1", "rag_p1_v1")
        self.assertIsNotNone(active)
        self.assertEqual(active.placement_id, plan.replacement_records[0].placement_id)
        self.assertEqual(active.state, "active")
        self.assertEqual(
            [record.state for record in placement_repo.list_by_collection("rag_p1_v1")],
            ["stale", "active"],
        )


def _shards(count: int) -> list[RetrievalShard]:
    return [
        RetrievalShard(
            shard_id=f"shard-{index}",
            cluster_id="cluster",
            qdrant_endpoint=f"http://shard-{index}:6333",
        )
        for index in range(count)
    ]


def _down_shard() -> RetrievalShard:
    return RetrievalShard(
        shard_id="down",
        cluster_id="cluster",
        qdrant_endpoint="http://down:6333",
        state="down",
    )


if __name__ == "__main__":
    unittest.main()
