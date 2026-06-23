"""Placement registry repository implementations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from retrieval_service.placement.models import (
    PlacementRecord,
    RetrievalShard,
    RoutingPolicy,
)


class RetrievalShardRepository(Protocol):
    """Storage boundary for retrieval shard registry records."""

    def list_active(self) -> list[RetrievalShard]: ...

    def upsert(self, shard: RetrievalShard) -> None: ...

    def get(self, shard_id: str) -> RetrievalShard | None: ...


class PlacementRepository(Protocol):
    """Storage boundary for routing-key placement records."""

    def get_active(self, routing_key: str, collection_name: str) -> PlacementRecord | None: ...
    def list_by_collection(self, collection_name: str) -> list[PlacementRecord]: ...
    def save(self, record: PlacementRecord) -> None: ...
    def mark_state(self, placement_id: str, state: str) -> None: ...
    def next_version(self) -> int: ...


class RoutingPolicyRepository(Protocol):
    """Storage boundary for per-project retrieval routing policies."""

    def get_policy(self, project_id: str) -> RoutingPolicy | None: ...
    def save_policy(self, policy: RoutingPolicy) -> None: ...


class InMemoryRetrievalShardRepository:
    """In-memory shard registry for tests and local composition."""

    def __init__(self, shards: list[RetrievalShard] | None = None) -> None:
        self._shards = {shard.shard_id: shard for shard in shards or []}

    def list_active(self) -> list[RetrievalShard]:
        return [shard for shard in self._shards.values() if shard.state == "active"]

    def upsert(self, shard: RetrievalShard) -> None:
        self._shards[shard.shard_id] = shard

    def get(self, shard_id: str) -> RetrievalShard | None:
        return self._shards.get(shard_id)


class InMemoryPlacementRepository:
    """In-memory placement registry for tests and local composition."""

    def __init__(self, records: list[PlacementRecord] | None = None) -> None:
        self._records: dict[tuple[str, str], list[PlacementRecord]] = {}
        self._version = 0
        for record in records or []:
            self.save(record)

    def get_active(
        self,
        routing_key: str,
        collection_name: str,
    ) -> PlacementRecord | None:
        return next(
            (
                record
                for record in sorted(
                    self._records.get((routing_key, collection_name), []),
                    key=lambda item: item.placement_version,
                    reverse=True,
                )
                if record.state == "active"
            ),
            None,
        )

    def list_by_collection(self, collection_name: str) -> list[PlacementRecord]:
        return sorted(
            [
                record
                for (_routing_key, collection), records in self._records.items()
                if collection == collection_name
                for record in records
            ],
            key=lambda record: (record.routing_key, record.placement_version),
        )

    def save(self, record: PlacementRecord) -> None:
        key = (record.routing_key, record.collection_name)
        records = [
            existing
            for existing in self._records.get(key, [])
            if existing.placement_id != record.placement_id
        ]
        records.append(record)
        self._records[key] = records
        self._version = max(self._version, record.placement_version)

    def mark_state(self, placement_id: str, state: str) -> None:
        for key, records in self._records.items():
            self._records[key] = [
                PlacementRecord(
                    placement_id=record.placement_id,
                    placement_version=record.placement_version,
                    routing_key=record.routing_key,
                    primary_shard_id=record.primary_shard_id,
                    replica_shard_ids=record.replica_shard_ids,
                    collection_name=record.collection_name,
                    state=state,
                )
                if record.placement_id == placement_id
                else record
                for record in records
            ]

    def next_version(self) -> int:
        self._version += 1
        return self._version


class InMemoryRoutingPolicyRepository:
    """In-memory routing-policy registry for tests and local composition."""

    def __init__(self, policies: list[RoutingPolicy] | None = None) -> None:
        self._policies = {policy.project_id: policy for policy in policies or []}

    def get_policy(self, project_id: str) -> RoutingPolicy | None:
        return self._policies.get(project_id) or self._policies.get("*")

    def save_policy(self, policy: RoutingPolicy) -> None:
        self._policies[policy.project_id] = policy


class SQLitePlacementRegistry:
    """SQLite-backed shard and placement registry."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        with self._connect() as conn:
            _migrate_placement_table(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS retrieval_shards (
                    shard_id TEXT PRIMARY KEY,
                    cluster_id TEXT NOT NULL,
                    qdrant_endpoint TEXT NOT NULL,
                    weight INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    qps REAL NOT NULL,
                    queue_depth INTEGER NOT NULL,
                    cpu REAL NOT NULL,
                    memory REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_retrieval_shards_state
                    ON retrieval_shards(state);

                CREATE TABLE IF NOT EXISTS retrieval_placements (
                    placement_id TEXT NOT NULL,
                    routing_key TEXT NOT NULL,
                    collection_name TEXT NOT NULL,
                    placement_version INTEGER NOT NULL,
                    primary_shard_id TEXT NOT NULL,
                    replica_shard_ids_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    PRIMARY KEY (placement_id)
                );
                CREATE INDEX IF NOT EXISTS idx_retrieval_placements_key_state
                    ON retrieval_placements(routing_key, collection_name, state);
                CREATE INDEX IF NOT EXISTS idx_retrieval_placements_state
                    ON retrieval_placements(state);

                CREATE TABLE IF NOT EXISTS retrieval_routing_policies (
                    project_id TEXT PRIMARY KEY,
                    routing_mode TEXT NOT NULL,
                    bucket_count INTEGER NOT NULL,
                    replication_factor INTEGER NOT NULL,
                    read_fanout TEXT NOT NULL,
                    cache_affinity INTEGER NOT NULL
                );
                """
            )

    def list_active(self) -> list[RetrievalShard]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT shard_id, cluster_id, qdrant_endpoint, weight, state,
                       qps, queue_depth, cpu, memory
                  FROM retrieval_shards
                 WHERE state = 'active'
                 ORDER BY shard_id
                """
            ).fetchall()
        return [_shard_from_row(row) for row in rows]

    def upsert(self, shard: RetrievalShard) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_shards (
                    shard_id, cluster_id, qdrant_endpoint, weight, state,
                    qps, queue_depth, cpu, memory
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shard_id) DO UPDATE SET
                    cluster_id = excluded.cluster_id,
                    qdrant_endpoint = excluded.qdrant_endpoint,
                    weight = excluded.weight,
                    state = excluded.state,
                    qps = excluded.qps,
                    queue_depth = excluded.queue_depth,
                    cpu = excluded.cpu,
                    memory = excluded.memory
                """,
                (
                    shard.shard_id,
                    shard.cluster_id,
                    shard.qdrant_endpoint,
                    shard.weight,
                    shard.state,
                    shard.qps,
                    shard.queue_depth,
                    shard.cpu,
                    shard.memory,
                ),
            )

    def get(self, shard_id: str) -> RetrievalShard | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT shard_id, cluster_id, qdrant_endpoint, weight, state,
                       qps, queue_depth, cpu, memory
                  FROM retrieval_shards
                 WHERE shard_id = ?
                """,
                (shard_id,),
            ).fetchone()
        if row is None:
            return None
        return _shard_from_row(row)

    def get_active(
        self,
        routing_key: str,
        collection_name: str,
    ) -> PlacementRecord | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT placement_id, placement_version, routing_key,
                       primary_shard_id, replica_shard_ids_json,
                       collection_name, state
                  FROM retrieval_placements
                 WHERE routing_key = ?
                   AND collection_name = ?
                   AND state = 'active'
                """,
                (routing_key, collection_name),
            ).fetchone()
        if row is None:
            return None
        return _placement_from_row(row)

    def list_by_collection(self, collection_name: str) -> list[PlacementRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT placement_id, placement_version, routing_key,
                       primary_shard_id, replica_shard_ids_json,
                       collection_name, state
                  FROM retrieval_placements
                 WHERE collection_name = ?
                 ORDER BY routing_key, placement_version
                """,
                (collection_name,),
            ).fetchall()
        return [_placement_from_row(row) for row in rows]

    def save(self, record: PlacementRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_placements (
                    placement_id, routing_key, collection_name,
                    placement_version, primary_shard_id,
                    replica_shard_ids_json, state
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(placement_id) DO UPDATE SET
                    routing_key = excluded.routing_key,
                    collection_name = excluded.collection_name,
                    placement_version = excluded.placement_version,
                    primary_shard_id = excluded.primary_shard_id,
                    replica_shard_ids_json = excluded.replica_shard_ids_json,
                    state = excluded.state
                """,
                (
                    record.placement_id,
                    record.routing_key,
                    record.collection_name,
                    record.placement_version,
                    record.primary_shard_id,
                    json.dumps(list(record.replica_shard_ids)),
                    record.state,
                ),
            )

    def mark_state(self, placement_id: str, state: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE retrieval_placements
                   SET state = ?
                 WHERE placement_id = ?
                """,
                (state, placement_id),
            )

    def next_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(placement_version), 0) + 1 FROM retrieval_placements"
            ).fetchone()
        return int(row[0])

    def get_policy(self, project_id: str) -> RoutingPolicy | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT project_id, routing_mode, bucket_count,
                       replication_factor, read_fanout, cache_affinity
                  FROM retrieval_routing_policies
                 WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            if row is None and project_id != "*":
                row = conn.execute(
                    """
                    SELECT project_id, routing_mode, bucket_count,
                           replication_factor, read_fanout, cache_affinity
                      FROM retrieval_routing_policies
                     WHERE project_id = '*'
                    """,
                ).fetchone()
        if row is None:
            return None
        return _policy_from_row(row)

    def save_policy(self, policy: RoutingPolicy) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_routing_policies (
                    project_id, routing_mode, bucket_count, replication_factor,
                    read_fanout, cache_affinity
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    routing_mode = excluded.routing_mode,
                    bucket_count = excluded.bucket_count,
                    replication_factor = excluded.replication_factor,
                    read_fanout = excluded.read_fanout,
                    cache_affinity = excluded.cache_affinity
                """,
                (
                    policy.project_id,
                    policy.routing_mode,
                    policy.bucket_count,
                    policy.replication_factor,
                    policy.read_fanout,
                    1 if policy.cache_affinity else 0,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)


def _shard_from_row(row: sqlite3.Row) -> RetrievalShard:
    return RetrievalShard(
        shard_id=str(row["shard_id"]),
        cluster_id=str(row["cluster_id"]),
        qdrant_endpoint=str(row["qdrant_endpoint"]),
        weight=int(row["weight"]),
        state=str(row["state"]),
        qps=float(row["qps"]),
        queue_depth=int(row["queue_depth"]),
        cpu=float(row["cpu"]),
        memory=float(row["memory"]),
    )


def _placement_from_row(row: sqlite3.Row) -> PlacementRecord:
    return PlacementRecord(
        placement_id=str(row["placement_id"]),
        placement_version=int(row["placement_version"]),
        routing_key=str(row["routing_key"]),
        primary_shard_id=str(row["primary_shard_id"]),
        replica_shard_ids=tuple(json.loads(row["replica_shard_ids_json"])),
        collection_name=str(row["collection_name"]),
        state=str(row["state"]),
    )


def _policy_from_row(row: sqlite3.Row) -> RoutingPolicy:
    return RoutingPolicy(
        project_id=str(row["project_id"]),
        routing_mode=str(row["routing_mode"]),
        bucket_count=int(row["bucket_count"]),
        replication_factor=int(row["replication_factor"]),
        read_fanout=str(row["read_fanout"]),
        cache_affinity=bool(int(row["cache_affinity"])),
    )


def _migrate_placement_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'retrieval_placements'"
    ).fetchone()
    if row is None:
        return
    columns = conn.execute("PRAGMA table_info(retrieval_placements)").fetchall()
    primary_keys = {str(column[1]): int(column[5]) for column in columns if int(column[5])}
    if primary_keys == {"placement_id": 1}:
        return

    conn.executescript(
        """
        ALTER TABLE retrieval_placements RENAME TO retrieval_placements_legacy;
        CREATE TABLE retrieval_placements (
            placement_id TEXT NOT NULL,
            routing_key TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            placement_version INTEGER NOT NULL,
            primary_shard_id TEXT NOT NULL,
            replica_shard_ids_json TEXT NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (placement_id)
        );
        INSERT INTO retrieval_placements (
            placement_id, routing_key, collection_name, placement_version,
            primary_shard_id, replica_shard_ids_json, state
        )
        SELECT placement_id, routing_key, collection_name, placement_version,
               primary_shard_id, replica_shard_ids_json, state
          FROM retrieval_placements_legacy;
        DROP TABLE retrieval_placements_legacy;
        """
    )
