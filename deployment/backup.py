"""Automated backup for the broker-first RAG stack.

Snapshots every Postgres durable store (``pg_dump`` custom format) plus Qdrant
collection snapshots into a timestamped backup directory, then rotates old
backups. Restore steps live in docs/operations.md §6.

Usage:

    python -m deployment.backup \
        --root /backup/rag \
        --pg-url postgresql://rag:...@postgres:5432/rag \
        --qdrant-url http://qdrant:6333 \
        --keep 7

In the production compose this runs as the ``backup`` service (profile
``backup``); schedule it from host cron or a k8s CronJob.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from shared.postgres import pg_dsn

logger = logging.getLogger(__name__)

_BACKUP_PREFIX = "rag-backup-"


def snapshot_postgres(dsn: str, dest_dir: Path) -> Path:
    """Dump one Postgres database with pg_dump in custom format."""
    dbname = urlparse(dsn).path.lstrip("/") or "rag"
    dest_path = dest_dir / f"{dbname}.dump"
    subprocess.run(["pg_dump", "-Fc", "-f", str(dest_path), dsn], check=True)
    logger.info("backed up postgres db=%s -> %s", dbname, dest_path)
    return dest_path


def qdrant_collection_names(base_url: str, *, timeout: float = 15.0) -> list[str]:
    response = httpx.get(f"{base_url}/collections", timeout=timeout)
    response.raise_for_status()
    result = response.json().get("result", {})
    collections = result.get("collections", []) if isinstance(result, dict) else result
    return [item["name"] for item in collections if isinstance(item, dict)]


def snapshot_qdrant_collections(
    base_url: str,
    dest_dir: Path,
    *,
    collections: list[str] | None = None,
    timeout: float = 120.0,
) -> list[Path]:
    """Create and download a snapshot for each named Qdrant collection."""
    names = collections or qdrant_collection_names(base_url)
    created: list[Path] = []
    for name in names:
        create = httpx.post(f"{base_url}/collections/{name}/snapshots", timeout=timeout)
        create.raise_for_status()
        snapshot_name = create.json()["result"]["name"]
        download = httpx.get(
            f"{base_url}/collections/{name}/snapshots/{snapshot_name}",
            timeout=timeout,
        )
        download.raise_for_status()
        dest_path = dest_dir / f"{name}-{snapshot_name}.snapshot"
        dest_path.write_bytes(download.content)
        created.append(dest_path)
        logger.info("backed up qdrant collection=%s snapshot=%s", name, dest_path)
    return created


def rotate(backup_root: Path, keep: int) -> list[Path]:
    """Delete oldest backups beyond ``keep``; returns removed paths."""
    backups = sorted(
        p for p in backup_root.iterdir() if p.is_dir() and p.name.startswith(_BACKUP_PREFIX)
    )
    removed: list[Path] = []
    for stale in backups[:-keep] if keep > 0 else backups:
        shutil.rmtree(stale)
        removed.append(stale)
    if removed:
        logger.info("rotated %s old backup(s)", len(removed))
    return removed


def backup_all(
    *,
    backup_root: Path,
    pg_urls: list[str],
    qdrant_url: str = "",
    qdrant_collections: list[str] | None = None,
    keep: int = 7,
) -> Path:
    """Run a full backup; returns the timestamped backup directory."""
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = backup_root / f"{_BACKUP_PREFIX}{stamp}"
    dest.mkdir(parents=True, exist_ok=False)

    pg_dest = dest / "postgres"
    pg_dest.mkdir()
    for dsn in pg_urls:
        try:
            snapshot_postgres(dsn, pg_dest)
        except subprocess.CalledProcessError as exc:
            logger.warning("postgres backup failed dsn=%s error=%s", dsn, exc)

    if qdrant_url:
        qdrant_dest = dest / "qdrant"
        qdrant_dest.mkdir()
        try:
            snapshot_qdrant_collections(
                qdrant_url,
                qdrant_dest,
                collections=qdrant_collections,
            )
        except httpx.HTTPError as exc:
            logger.warning("qdrant backup failed url=%s error=%s", qdrant_url, exc)

    rotate(backup_root, keep)
    logger.info("backup complete dir=%s", dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up RAG Postgres + Qdrant state.")
    parser.add_argument("--root", required=True, help="Backup destination root directory.")
    parser.add_argument(
        "--pg-url",
        action="append",
        default=[],
        help="Postgres DSN to dump (repeatable; defaults to RAG_POSTGRES_URL).",
    )
    parser.add_argument("--qdrant-url", default="", help="Qdrant HTTP base URL, e.g. http://qdrant:6333.")
    parser.add_argument("--qdrant-collection", action="append", default=[], help="Restrict Qdrant snapshots to this collection (repeatable).")
    parser.add_argument("--keep", type=int, default=7, help="Number of backups to retain (default 7).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    backup_all(
        backup_root=Path(args.root),
        pg_urls=args.pg_url or [pg_dsn()],
        qdrant_url=args.qdrant_url,
        qdrant_collections=args.qdrant_collection or None,
        keep=args.keep,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
