"""Postgres retrieval stores tests (response cache + placement registry).

Run against the compose ``postgres`` service by setting ``RETRIEVAL_TEST_DB_URL``
(e.g. ``postgresql://rag:...@postgres:5432/rag``); skipped when unset.
"""

from __future__ import annotations

import os
import time

import pytest

from retrieval_service.placement.models import (
    PlacementRecord,
    RetrievalShard,
    RoutingPolicy,
)
from retrieval_service.placement.repository import PostgresPlacementRegistry
from retrieval_service.services.cache import PostgresTier2ResponseCache

TEST_DB_URL = os.environ.get("RETRIEVAL_TEST_DB_URL")


def _dsn() -> str:
    if not TEST_DB_URL:
        pytest.skip("RETRIEVAL_TEST_DB_URL is not set; skipping Postgres retrieval tests")
    return TEST_DB_URL


@pytest.fixture
async def cache() -> PostgresTier2ResponseCache:
    repository = PostgresTier2ResponseCache(_dsn(), ttl_seconds=60)
    await repository.initialize()
    async with repository._pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS responses CASCADE")
    await repository.initialize()
    yield repository
    await repository.close()


@pytest.mark.asyncio
async def test_cache_set_get_and_expiry(cache) -> None:
    assert await cache.get("p1", "u1", "k1") is None
    await cache.set("p1", "u1", "k1", "hello")
    assert await cache.get("p1", "u1", "k1") == "hello"
    await cache.set("p1", "u1", "k1", "world")
    assert await cache.get("p1", "u1", "k1") == "world"


@pytest.mark.asyncio
async def test_cache_invalidate(cache) -> None:
    await cache.set("p1", "u1", "k1", "a")
    await cache.set("p2", "u1", "k1", "b")
    await cache.invalidate_user("p1", "u1")
    assert await cache.get("p1", "u1", "k1") is None
    assert await cache.get("p2", "u1", "k1") == "b"
    await cache.set("p1", "u1", "k1", "a")
    await cache.invalidate_project("p1")
    assert await cache.get("p1", "u1", "k1") is None


@pytest.mark.asyncio
async def test_cache_clear_expired(cache) -> None:
    await cache.set("p1", "u1", "k1", "a")
    removed = await cache.clear_expired()
    assert removed == 0
    async with cache._pool.connection() as conn:
        await conn.execute(
            "UPDATE responses SET expires_at = %s WHERE project_id = 'p1'",
            (time.time() - 10,),
        )
    assert await cache.clear_expired() >= 1
    assert await cache.get("p1", "u1", "k1") is None


@pytest.fixture
def registry() -> PostgresPlacementRegistry:
    repository = PostgresPlacementRegistry(_dsn())
    with repository._connect() as conn:
        conn.execute(
            "DROP TABLE IF EXISTS retrieval_routing_policies, retrieval_placements,"
            " retrieval_shards CASCADE"
        )
    repository.initialize()
    yield repository


def test_shard_registry_roundtrip(registry) -> None:
    shard = RetrievalShard(
        shard_id="s1",
        cluster_id="local",
        qdrant_endpoint="http://qdrant:6333",
        weight=100,
        qps=1.0,
    )
    assert registry.list_active() == []
    registry.upsert(shard)
    got = registry.get("s1")
    assert got is not None and got.qdrant_endpoint == "http://qdrant:6333"
    assert [s.shard_id for s in registry.list_active()] == ["s1"]
    registry.upsert(RetrievalShard(shard_id="s1", cluster_id="local", qdrant_endpoint="http://x", state="inactive"))
    assert registry.get("s1").state == "inactive"
    assert registry.list_active() == []


def test_placement_save_active_and_version(registry) -> None:
    assert registry.next_version() == 1
    registry.save(
        PlacementRecord(
            placement_id="pl-1",
            placement_version=1,
            routing_key="rk-1",
            primary_shard_id="s1",
            replica_shard_ids=("s2",),
            collection_name="docs",
        )
    )
    active = registry.get_active("rk-1", "docs")
    assert active is not None and active.primary_shard_id == "s1"
    assert registry.list_by_collection("docs")[0].routing_key == "rk-1"
    registry.mark_state("pl-1", "inactive")
    assert registry.get_active("rk-1", "docs") is None
    assert registry.next_version() == 2


def test_routing_policy_default_fallback(registry) -> None:
    policy = RoutingPolicy(project_id="*", routing_mode="project_single")
    registry.save_policy(policy)
    assert registry.get_policy("p1").routing_mode == "project_single"
    project_policy = RoutingPolicy(project_id="p1", routing_mode="user_bucket", bucket_count=8)
    registry.save_policy(project_policy)
    assert registry.get_policy("p1").bucket_count == 8
