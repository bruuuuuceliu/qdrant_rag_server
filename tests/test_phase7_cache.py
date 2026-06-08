"""Phase 7 tests: Tier 1 and Tier 2 caches."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from retrieval_service.services.cache import (
    Tier1MemoryCache,
    Tier2ResponseCache,
    _hash_key,
)


class HashKeyTest(unittest.TestCase):
    def test_same_inputs_same_hash(self) -> None:
        self.assertEqual(
            _hash_key("a", "b", "c"),
            _hash_key("a", "b", "c"),
        )

    def test_different_inputs_different_hash(self) -> None:
        self.assertNotEqual(
            _hash_key("a", "b"),
            _hash_key("a", "c"),
        )


class Tier1MemoryCacheTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cache = Tier1MemoryCache(
            max_entries_per_project=3,
            ttl_seconds=60,
        )

    async def test_get_returns_none_for_missing_key(self) -> None:
        self.assertIsNone(await self.cache.get("p1", "k1"))

    async def test_set_and_get_round_trip(self) -> None:
        await self.cache.set("p1", "k1", {"chunks": [1, 2, 3]})
        result = await self.cache.get("p1", "k1")
        self.assertEqual(result, {"chunks": [1, 2, 3]})

    async def test_cache_hit_moves_key_to_end(self) -> None:
        await self.cache.set("p1", "k1", "a")
        await self.cache.set("p1", "k2", "b")
        await self.cache.set("p1", "k3", "c")
        await self.cache.get("p1", "k1")  # moves k1 to end
        await self.cache.set("p1", "k4", "d")  # evicts k2 (LRU)

        self.assertIsNotNone(await self.cache.get("p1", "k1"))
        self.assertIsNone(await self.cache.get("p1", "k2"))

    async def test_evicts_oldest_when_full(self) -> None:
        await self.cache.set("p1", "k1", "a")
        await self.cache.set("p1", "k2", "b")
        await self.cache.set("p1", "k3", "c")
        await self.cache.set("p1", "k4", "d")

        self.assertIsNone(await self.cache.get("p1", "k1"))
        self.assertIsNotNone(await self.cache.get("p1", "k4"))

    async def test_invalidate_project_clears_all_entries(self) -> None:
        await self.cache.set("p1", "k1", "a")
        await self.cache.set("p1", "k2", "b")

        await self.cache.invalidate_project("p1")

        self.assertIsNone(await self.cache.get("p1", "k1"))

    async def test_invalidate_project_does_not_affect_other(self) -> None:
        await self.cache.set("p1", "k1", "a")
        await self.cache.set("p2", "k1", "b")

        await self.cache.invalidate_project("p1")

        self.assertIsNotNone(await self.cache.get("p2", "k1"))

    async def test_clear_expired_removes_stale_entries(self) -> None:
        cache = Tier1MemoryCache(max_entries_per_project=10, ttl_seconds=0)
        await cache.set("p1", "k1", "a")
        await cache.set("p2", "k2", "b")

        import asyncio
        await asyncio.sleep(0.01)

        removed = await cache.clear_expired()
        self.assertGreaterEqual(removed, 2)


class Tier2ResponseCacheTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "response_cache.db"
        self.cache = Tier2ResponseCache(db_path=self.db_path, ttl_seconds=60)
        await self.cache.initialize()

    async def test_set_and_get_round_trip(self) -> None:
        await self.cache.set("p1", "u1", "key1", "Hello, World!")
        result = await self.cache.get("p1", "u1", "key1")
        self.assertEqual(result, "Hello, World!")

    async def test_get_returns_none_for_missing_key(self) -> None:
        self.assertIsNone(await self.cache.get("p1", "u1", "missing"))

    async def test_different_user_same_key_is_isolated(self) -> None:
        await self.cache.set("p1", "u1", "key1", "data_u1")
        await self.cache.set("p1", "u2", "key1", "data_u2")

        self.assertEqual(await self.cache.get("p1", "u1", "key1"), "data_u1")
        self.assertEqual(await self.cache.get("p1", "u2", "key1"), "data_u2")

    async def test_invalidate_user_clears_user_entries(self) -> None:
        await self.cache.set("p1", "u1", "k1", "a")
        await self.cache.set("p1", "u2", "k1", "b")

        await self.cache.invalidate_user("p1", "u1")

        self.assertIsNone(await self.cache.get("p1", "u1", "k1"))
        self.assertIsNotNone(await self.cache.get("p1", "u2", "k1"))

    async def test_invalidate_project_clears_all(self) -> None:
        await self.cache.set("p1", "u1", "k1", "a")
        await self.cache.set("p2", "u1", "k1", "b")

        await self.cache.invalidate_project("p1")

        self.assertIsNone(await self.cache.get("p1", "u1", "k1"))
        self.assertIsNotNone(await self.cache.get("p2", "u1", "k1"))

    async def test_expired_entry_returns_none(self) -> None:
        cache = Tier2ResponseCache(db_path=self.db_path, ttl_seconds=0)
        await cache.set("p1", "u1", "key1", "expired")

        import asyncio
        await asyncio.sleep(0.1)

        self.assertIsNone(await cache.get("p1", "u1", "key1"))


if __name__ == "__main__":
    unittest.main()
