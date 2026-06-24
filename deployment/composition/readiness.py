"""Deployment readiness checks for the broker-first local composition."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from broker_service import (
    BrokerSettings,
    broker_health,
    create_redpanda_admin,
    parse_broker_lag_targets,
)
from redis_status_node import RedisStatusSettings, RedisTaskStatusStore, TaskStatusRecord
from sqlite_node import SQLiteNodeSettings, SQLiteNodeService
from storage_node.config import StorageNodeSettings


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    ready: bool
    details: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ready": self.ready,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.ready for check in self.checks)

    def to_payload(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "checks": [check.to_payload() for check in self.checks],
        }


async def check_broker(values: dict[str, str] | None = None) -> ReadinessCheck:
    values = values or dict(os.environ)
    details: dict[str, Any]
    admin = None
    try:
        settings = BrokerSettings.from_values(values)
        admin = create_redpanda_admin(settings)
        await admin.start()
        lag_targets = parse_broker_lag_targets(values.get("BROKER_LAG_TARGETS"))
        try:
            health = await broker_health(admin, lag_targets=lag_targets)
        except Exception as exc:
            health = await broker_health(admin)
            health["lag_error"] = str(exc)
            health["lag_target_count"] = len(lag_targets)
        details = dict(health)
        ready = bool(health.get("ok"))
    except Exception as exc:
        ready = False
        details = {"error": str(exc)}
    finally:
        if admin is not None:
            try:
                await admin.stop()
            except Exception as exc:
                details.setdefault("stop_error", str(exc))
    return ReadinessCheck(
        name="broker",
        ready=ready,
        details=details,
    )


async def check_redis(values: dict[str, str] | None = None) -> ReadinessCheck:
    values = values or dict(os.environ)
    settings = RedisStatusSettings.from_values(values)
    store = RedisTaskStatusStore(settings=settings)
    task_id = "readiness"
    details: dict[str, Any] = {"url": settings.url, "key_prefix": settings.key_prefix}
    try:
        ping = await store.ping()
        await store.set_status(TaskStatusRecord(task_id=task_id, status="completed"), ttl_seconds=60)
        details["ttl"] = await store.ttl(task_id)
        ready = bool(ping) and int(details["ttl"]) > 0
    except Exception as exc:
        ready = False
        details["error"] = str(exc)
    finally:
        await store.client.aclose()
    return ReadinessCheck(name="redis", ready=ready, details=details)


async def check_storage(values: dict[str, str] | None = None) -> ReadinessCheck:
    values = values or dict(os.environ)
    settings = StorageNodeSettings.from_values(values)
    root = Path(settings.storage_root)
    details = {"storage_root": str(root)}
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".readiness"
        probe.write_text("ok", encoding="utf-8")
        ready = probe.read_text(encoding="utf-8") == "ok"
        probe.unlink(missing_ok=True)
    except Exception as exc:
        ready = False
        details["error"] = str(exc)
    return ReadinessCheck(name="storage", ready=ready, details=details)


async def check_sqlite(values: dict[str, str] | None = None) -> ReadinessCheck:
    values = values or dict(os.environ)
    settings = SQLiteNodeSettings.from_values(values)
    service = SQLiteNodeService(database_root=settings.database_root)
    details = {"database_root": str(service.database_root)}
    try:
        await service.initialize()
        db_path = await service.allocate_database(
            owner_service="sqlite_node",
            database_name="readiness",
            purpose="deployment readiness probe",
        )
        await service.record_schema_version(
            owner_service="sqlite_node",
            database_name="readiness",
            schema_name="readiness",
            version=1,
        )
        health = await service.record_health_check(
            owner_service="sqlite_node",
            database_name="readiness",
            ok=db_path.parent.exists(),
        )
        ready = db_path.parent.exists() and service.metadata_db_path.exists() and health.ok
        details["allocated_path"] = str(db_path)
        details["metadata_db"] = str(service.metadata_db_path)
    except Exception as exc:
        ready = False
        details["error"] = str(exc)
    return ReadinessCheck(name="sqlite", ready=ready, details=details)


async def check_qdrant(values: dict[str, str] | None = None) -> ReadinessCheck:
    values = values or dict(os.environ)
    host = values.get("RAG_QDRANT_HOST", "localhost")
    port = values.get("RAG_QDRANT_PORT", "6333")
    url = f"http://{host}:{port}/collections"
    details = {"url": url}
    try:
        with urlopen(url, timeout=3) as response:
            ready = 200 <= int(response.status) < 300
            details["status"] = response.status
    except (OSError, URLError) as exc:
        ready = False
        details["error"] = str(exc)
    return ReadinessCheck(name="qdrant", ready=ready, details=details)


async def broker_first_report(
    *,
    include_qdrant: bool = True,
    values: dict[str, str] | None = None,
) -> ReadinessReport:
    values = values or dict(os.environ)
    checks = [
        await check_broker(values),
        await check_redis(values),
        await check_storage(values),
        await check_sqlite(values),
    ]
    if include_qdrant:
        checks.append(await check_qdrant(values))
    return ReadinessReport(tuple(checks))


async def _run(args: argparse.Namespace) -> int:
    report = await broker_first_report(include_qdrant=not args.skip_qdrant)
    print(json.dumps(report.to_payload(), sort_keys=True))
    return 0 if report.ready else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Check broker-first deployment readiness.")
    parser.add_argument("--skip-qdrant", action="store_true", help="Do not check Qdrant readiness.")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
