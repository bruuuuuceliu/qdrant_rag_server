"""Automated backup module tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from deployment.backup import (
    backup_all,
    qdrant_collection_names,
    rotate,
    snapshot_postgres,
    snapshot_qdrant_collections,
)

DSN = "postgresql://rag:rag@localhost:5432/rag"


def test_snapshot_postgres_invokes_pg_dump(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        dest = Path(argv[argv.index("-f") + 1])
        dest.write_bytes(b"dump-bytes")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    snapshot_path = snapshot_postgres(DSN, dest_dir)

    assert captured["argv"] == ["pg_dump", "-Fc", "-f", str(dest_dir / "rag.dump"), DSN]
    assert snapshot_path == dest_dir / "rag.dump"
    assert snapshot_path.read_bytes() == b"dump-bytes"


def test_rotate_keeps_newest(tmp_path: Path) -> None:
    for name in ("rag-backup-1", "rag-backup-2", "rag-backup-3", "other"):
        (tmp_path / name).mkdir()
    removed = rotate(tmp_path, keep=2)
    remaining = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert removed == [tmp_path / "rag-backup-1"]
    assert remaining == ["other", "rag-backup-2", "rag-backup-3"]


def test_qdrant_collection_names(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"result": {"collections": [{"name": "agent_memory"}, {"name": "docs"}]}}

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        assert url == "http://qdrant:6333/collections"
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)
    assert qdrant_collection_names("http://qdrant:6333") == ["agent_memory", "docs"]


def test_snapshot_qdrant_collections_creates_and_downloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class PostResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"result": {"name": "snap-1"}}

    class GetResponse:
        def raise_for_status(self) -> None:
            pass

        @property
        def content(self) -> bytes:
            return b"snapshot-bytes"

    posted: list[str] = []

    def fake_post(url: str, **kwargs: object) -> PostResponse:
        posted.append(url)
        return PostResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: GetResponse())

    dest = tmp_path / "snaps"
    dest.mkdir()
    created = snapshot_qdrant_collections("http://qdrant:6333", dest, collections=["agent_memory"])

    assert posted == ["http://qdrant:6333/collections/agent_memory/snapshots"]
    assert created == [dest / "agent_memory-snap-1.snapshot"]
    assert created[0].read_bytes() == b"snapshot-bytes"


def test_backup_all_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(argv, **kwargs):
        dest = Path(argv[argv.index("-f") + 1])
        dest.write_bytes(b"dump-bytes")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    class PostResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"result": {"name": "s1"}}

    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kwargs: PostResponse(),
    )

    class GetResponse:
        def __init__(self, url: str) -> None:
            self._url = url

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"result": {"collections": [{"name": "agent_memory"}]}}

        @property
        def content(self) -> bytes:
            return b"x"

    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: GetResponse(url))

    backup_root = tmp_path / "backups"
    dest = backup_all(
        backup_root=backup_root,
        pg_urls=[DSN],
        qdrant_url="http://qdrant:6333",
        keep=1,
    )

    assert dest.exists()
    assert (dest / "postgres" / "rag.dump").exists()
    assert (dest / "qdrant" / "agent_memory-s1.snapshot").exists()
