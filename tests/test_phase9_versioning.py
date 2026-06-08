"""Phase 9 tests: version manager and embedding versioning."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from retrieval_service.config import SQLiteProjectConfigRepository
from retrieval_service.core.models import BaseProjectConfig
from retrieval_service.versioning import VersionManager, VersionNotFoundError


class VersionManagerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "config.db"
        self.config_repo = SQLiteProjectConfigRepository(self.db_path)
        await self.config_repo.initialize()

        await self.config_repo.upsert_project(
            BaseProjectConfig(
                project_id="p1",
                project_type="website",
                active_embedding_version="v1",
                embedding_model="bge-base",
                reranker_model="bge-reranker-base",
            )
        )

        self.version_manager = VersionManager(
            config_repo=self.config_repo,
            grace_period_seconds=0,
        )
        await self.version_manager.initialize()

    async def test_create_new_version_not_active_by_default(self) -> None:
        info = await self.version_manager.create_new_version(
            "p1", "v2", embedding_model="bge-base", chunker_version="v1"
        )
        self.assertEqual(info.version, "v2")
        self.assertFalse(info.is_active)
        self.assertEqual(info.collection_name, "rag_p1_v2")

    async def test_create_new_version_and_make_active(self) -> None:
        await self.version_manager.create_new_version(
            "p1", "v2", embedding_model="bge-base", make_active=True
        )
        active = await self.version_manager.get_active_version("p1")
        self.assertEqual(active.version, "v2")

        config = await self.config_repo.get_project_config("p1")
        self.assertEqual(config.active_embedding_version, "v2")

    async def test_list_versions_returns_all(self) -> None:
        await self.version_manager.create_new_version("p1", "v2")
        await self.version_manager.create_new_version("p1", "v3")
        versions = await self.version_manager.list_versions("p1")
        self.assertEqual(len(versions), 2)

    async def test_activate_version_atomic_swap(self) -> None:
        await self.version_manager.create_new_version("p1", "v2", make_active=True)
        await self.version_manager.create_new_version("p1", "v3")
        await self.version_manager.activate_version("p1", "v3")

        active = await self.version_manager.get_active_version("p1")
        self.assertEqual(active.version, "v3")

        config = await self.config_repo.get_project_config("p1")
        self.assertEqual(config.active_embedding_version, "v3")

        versions = await self.version_manager.list_versions("p1")
        for v in versions:
            if v.version != "v3":
                self.assertFalse(v.is_active)

    async def test_activate_version_raises_for_missing(self) -> None:
        with self.assertRaises(VersionNotFoundError):
            await self.version_manager.activate_version("p1", "v99")

    async def test_delete_expired_versions_removes_old(self) -> None:
        await self.version_manager.create_new_version("p1", "v1", make_active=True)
        await self.version_manager.create_new_version("p1", "v2")
        await self.version_manager.create_new_version("p1", "v3")
        await self.version_manager.activate_version("p1", "v3")

        deleted = await self.version_manager.delete_expired_versions("p1")
        self.assertGreaterEqual(len(deleted), 1)

        remaining = await self.version_manager.list_versions("p1")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].version, "v3")

    async def test_get_active_version_returns_none_when_none_active(self) -> None:
        await self.version_manager.create_new_version("p1", "v2")
        info = await self.version_manager.get_active_version("p1")
        self.assertIsNone(info)


if __name__ == "__main__":
    unittest.main()
