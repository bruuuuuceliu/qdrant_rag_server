"""Automated backup module tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from deployment.backup import (
    backup_all,
    collect_sqlite_paths,
    qdrant_collection_names,
    rotate,
    snapshot_qdrant_collections,
    snapshot_sqlite,
)


def _make_db(path: Path, *, table: str = "notes", row: str = "hello") -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(f"CREATE TABLE {table} (value TEXT)")
        connection.execute(f"INSERT INTO {table} VALUES (?)", (row,))
        connection.commit()
    finally:
        connection.close()


def test_snapshot_sqlite_copies_data(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    _make_db(source)
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()

    snapshot_path = snapshot_sqlite(source, dest_dir)

    connection = sqlite3.connect(str(snapshot_path))
    try:
        row = connection.execute("SELECT value FROM notes").fetchone()
    finally:
        connection.close()
    assert row == ("hello",)


def test_restore_drill_backup_then_restore(tmp_path: Path) -> None:
    """Restore drill: a backup file must restore cleanly into a scratch DB."""
    source = tmp_path / "state.db"
    connection = sqlite3.connect(str(source))
    connection.execute("CREATE TABLE docs (doc_id TEXT, text TEXT)")
    connection.execute("INSERT INTO docs VALUES ('d1', 'alpha'), ('d2', 'beta')")
    connection.commit()
    connection.close()

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    snapshot_path = snapshot_sqlite(source, out_dir)

    # Restore into a scratch path and verify both rows survive the round-trip.
    restored = tmp_path / "restored.db"
    restored.write_bytes(snapshot_path.read_bytes())
    verify = sqlite3.connect(str(restored))
    try:
        rows = verify.execute("SELECT doc_id, text FROM docs ORDER BY doc_id").fetchall()
    finally:
        verify.close()
    assert rows == [("d1", "alpha"), ("d2", "beta")]


def test_snapshot_sqlite_under_wal(tmp_path: Path) -> None:
    source = tmp_path / "wal.db"
    _make_db(source)
    connection = sqlite3.connect(str(source))
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE extra (value TEXT)")
    connection.execute("INSERT INTO extra VALUES ('wal-row')")
    connection.commit()
    connection.close()

    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    snapshot_path = snapshot_sqlite(source, dest_dir)

    verify = sqlite3.connect(str(snapshot_path))
    try:
        row = verify.execute("SELECT value FROM extra").fetchone()
    finally:
        verify.close()
    assert row == ("wal-row",)


def test_collect_sqlite_paths_finds_all_dbs(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    _make_db(tmp_path / "a.db")
    _make_db(tmp_path / "nested" / "b.db")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    paths = collect_sqlite_paths(tmp_path)
    assert {p.name for p in paths} == {"a.db", "b.db"}


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
    sqlite_root = tmp_path / "data"
    sqlite_root.mkdir()
    _make_db(sqlite_root / "memory.db")

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
        sqlite_root=sqlite_root,
        qdrant_url="http://qdrant:6333",
        keep=1,
    )

    assert dest.exists()
    assert (dest / "sqlite" / "memory.db.bak").exists()
    assert (dest / "qdrant" / "agent_memory-s1.snapshot").exists()
