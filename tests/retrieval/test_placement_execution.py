"""Runtime placement execution helper tests."""

from __future__ import annotations

import unittest

from retrieval_service.placement import (
    InMemoryRetrievalShardRepository,
    PlacementExecutionTarget,
    PlacementStoreResolver,
    RetrievalShard,
    placement_cache_scope,
    placement_read_targets,
    placement_write_target,
    placement_write_targets,
)


class PlacementExecutionTest(unittest.IsolatedAsyncioTestCase):
    async def test_store_resolver_builds_store_from_shard_endpoint(self) -> None:
        default_store = object()
        made: list[dict[str, object]] = []

        def factory(**kwargs):
            made.append(kwargs)
            return {"store": kwargs}

        resolver = PlacementStoreResolver(
            default_store=default_store,
            shard_repository=InMemoryRetrievalShardRepository(
                [
                    RetrievalShard(
                        shard_id="s1",
                        cluster_id="c1",
                        qdrant_endpoint="http://qdrant-1:6333",
                    )
                ]
            ),
            store_factory=factory,
            default_vector_size=1536,
        )

        store = await resolver.resolve(
            PlacementExecutionTarget(
                routing_key="project:p1",
                shard_id="s1",
                collection_name="rag_p1_v1",
            )
        )

        self.assertEqual(store, {"store": {"url": "http://qdrant-1:6333", "default_vector_size": 1536}})
        self.assertEqual(len(made), 1)
        again = await resolver.resolve(
            PlacementExecutionTarget(
                routing_key="project:p1",
                shard_id="s1",
                collection_name="rag_p1_v1",
            )
        )
        self.assertIs(again, store)

    def test_targets_and_cache_scope_parse_plan(self) -> None:
        plan = {
            "placement_version": 3,
            "fanout": True,
            "targets": [
                {
                    "routing_key": "project:p1:b0",
                    "shard_id": "s1",
                    "collection_name": "rag_p1_b0",
                    "role": "primary",
                },
                {
                    "routing_key": "project:p1:b1",
                    "shard_id": "s2",
                    "collection_name": "rag_p1_b1",
                    "role": "primary",
                },
            ],
        }

        read_targets = placement_read_targets(plan, fallback_collection_name="fallback")
        write_target = placement_write_target(plan, fallback_collection_name="fallback")
        write_targets = placement_write_targets(plan, fallback_collection_name="fallback")

        self.assertEqual([target.collection_name for target in read_targets], ["rag_p1_b0", "rag_p1_b1"])
        self.assertEqual(write_target.shard_id, "s1")
        self.assertEqual([target.shard_id for target in write_targets], ["s1", "s2"])
        self.assertEqual(
            placement_cache_scope(plan),
            "v3|s1:project:p1:b0|s2:project:p1:b1",
        )

    def test_fallback_target_uses_request_collection(self) -> None:
        target = placement_write_target({}, fallback_collection_name="rag_p1_v1")

        self.assertEqual(target.collection_name, "rag_p1_v1")
        self.assertEqual(target.shard_id, "")


if __name__ == "__main__":
    unittest.main()
