# Database Placement Design

Status: database-side routing design with placement core implemented locally.

Operational scope now: one configured Qdrant endpoint is used for local runtime
execution. The placement registry and `placement_plan` messages are active so
the service path is ready for shard-aware routing later, but running multiple
database/Qdrant servers is design-only and intentionally not enabled yet.

Implemented now:

- `retrieval_service.placement` data models for scopes, policies, shards,
  placement records, targets, and plans
- stable hash helpers, routing-key resolvers, weighted rendezvous assignment,
  and top-N replica selection
- in-memory and SQLite shard/placement registries
- resolver that stores new placement records and reuses active records for
  normal requests
- local config loading and project-planning integration that attaches
  placement plans to ingest/search/delete work
- split ingestion forwarding of placement metadata to retrieval index requests

Still pending:

- per-project routing-policy persistence table
- live routing to separate Qdrant clients/endpoints per placement target
- bucketed search fanout, result merge, and readable replica failover
- shard-aware cache keys using `placement_version`, routing key, and shard ID
- explicit rebalance/migration execution

This design ignores KB and session scope. Database routing uses only project,
user, topic, document, and bucket identity.

## Goal

When request volume grows, one Qdrant/database server should not receive all
traffic. Retrieval data and cache should be placed across multiple retrieval
database shards, and every request should be routed to the shard that owns the
data.

Rule:

```text
Route by data ownership first, load balance by assignment/rebalance second.
```

Do not round-robin individual database requests. Random routing breaks cache
locality and can return incomplete data unless every database has a full copy.

## Ownership Split

```text
Project service owns:
  project_id, user_id, topic_id, document policy, visibility, filters

Retrieval/database placement owns:
  routing_key, bucket_id, shard_id, placement_version, collection, cache scope
```

Manager should not know Qdrant endpoints. It may carry opaque routing metadata,
but the retrieval placement layer resolves database targets.

## High-Level Flow

```text
Client
  -> Manager
  -> Project Service
      builds ProjectScope and project filters
  -> Retrieval Placement Resolver
      returns PlacementPlan
  -> Retrieval Shard(s)
      own Qdrant endpoint and shard-local cache
```

For ingest:

```text
project/user/topic/doc -> routing key -> placement -> retrieval shard -> Qdrant
```

For search:

```text
project/user/topic -> placement target(s) -> shard-local cache/search -> merge
```

## Data Structures

### ProjectScope

Business meaning of the request. This is project-service level information.

```python
@dataclass(frozen=True)
class ProjectScope:
    project_id: str
    user_id: str
    topic_id: str = ""
    doc_id: str = ""
    data_type: str = "project_document"
```

Example:

```json
{
  "project_id": "real-estate",
  "user_id": "user-42",
  "topic_id": "rentals",
  "doc_id": "house-123",
  "data_type": "project_document"
}
```

Short description: says what data the request touches, not where the database
lives.

### RoutingPolicy

Project-level policy that controls routing key construction.

```python
@dataclass(frozen=True)
class RoutingPolicy:
    project_id: str
    routing_mode: str
    bucket_count: int = 1
    replication_factor: int = 1
    read_fanout: str = "single"
    cache_affinity: bool = True
```

Supported `routing_mode` values:

```text
project_single
user_single
topic_single
user_bucketed
topic_bucketed
doc_bucketed
```

Short descriptions:

```text
project_single: all project data on one shard
user_single: each user's data on one shard
topic_single: each topic's data on one shard
user_bucketed: one hot user split across buckets
topic_bucketed: one hot topic split across buckets
doc_bucketed: whole project split by document buckets
```

Example:

```json
{
  "project_id": "real-estate",
  "routing_mode": "topic_bucketed",
  "bucket_count": 64,
  "replication_factor": 1,
  "read_fanout": "all_buckets",
  "cache_affinity": true
}
```

### RoutingKey

Stable key used to assign data to database shards.

```python
@dataclass(frozen=True)
class RoutingKey:
    value: str
```

Examples:

```text
project:real-estate
project:real-estate:user:user-42
project:real-estate:topic:rentals
project:real-estate:user:user-42:bucket:8
project:real-estate:topic:rentals:bucket:17
project:real-estate:doc_bucket:203
```

Short description: the hash input for placement and cache affinity.

### RetrievalShard

One database-serving unit. Each shard owns a Qdrant endpoint and local cache.

```python
@dataclass
class RetrievalShard:
    shard_id: str
    cluster_id: str
    qdrant_endpoint: str
    weight: int = 100
    state: str = "active"  # active, draining, readonly, down
    qps: float = 0.0
    queue_depth: int = 0
    cpu: float = 0.0
    memory: float = 0.0
```

Example:

```json
{
  "shard_id": "retrieval-03",
  "cluster_id": "retrieval-cluster-a",
  "qdrant_endpoint": "http://qdrant-03:6333",
  "weight": 100,
  "state": "active",
  "qps": 40,
  "queue_depth": 8,
  "cpu": 0.56,
  "memory": 0.62
}
```

### PlacementRecord

Persistent ownership record from routing key to retrieval shard.

```python
@dataclass(frozen=True)
class PlacementRecord:
    placement_id: str
    placement_version: int
    routing_key: str
    primary_shard_id: str
    replica_shard_ids: tuple[str, ...]
    collection_name: str
    state: str = "active"  # active, moving, draining, stale
```

Example:

```json
{
  "placement_id": "plc-123",
  "placement_version": 4,
  "routing_key": "project:real-estate:topic:rentals:bucket:17",
  "primary_shard_id": "retrieval-03",
  "replica_shard_ids": [],
  "collection_name": "rag_real-estate_v1",
  "state": "active"
}
```

Short description: the main database assignment record.

### PlacementPlan

Execution target list attached to ingest/search/delete work.

```python
@dataclass(frozen=True)
class PlacementTarget:
    routing_key: str
    shard_id: str
    collection_name: str
    role: str = "primary"

@dataclass(frozen=True)
class PlacementPlan:
    placement_version: int
    targets: tuple[PlacementTarget, ...]
    fanout: bool = False
```

Single-target example:

```json
{
  "placement_version": 4,
  "fanout": false,
  "targets": [
    {
      "routing_key": "project:real-estate:topic:rentals",
      "shard_id": "retrieval-03",
      "collection_name": "rag_real-estate_v1",
      "role": "primary"
    }
  ]
}
```

Fanout example:

```json
{
  "placement_version": 4,
  "fanout": true,
  "targets": [
    {"routing_key": "project:real-estate:topic:rentals:bucket:0", "shard_id": "retrieval-01", "collection_name": "rag_real-estate_v1"},
    {"routing_key": "project:real-estate:topic:rentals:bucket:1", "shard_id": "retrieval-02", "collection_name": "rag_real-estate_v1"},
    {"routing_key": "project:real-estate:topic:rentals:bucket:2", "shard_id": "retrieval-03", "collection_name": "rag_real-estate_v1"}
  ]
}
```

### CacheScope

Shard-local cache namespace.

```python
@dataclass(frozen=True)
class CacheScope:
    placement_version: int
    shard_id: str
    collection_name: str
    routing_key: str
```

Cache key:

```python
cache_key = hash(
    placement_version,
    shard_id,
    collection_name,
    routing_key,
    query_text,
    retrieval_filter_hash,
    retrieval_config_hash,
)
```

Short description: keeps cache local to the shard that owns the data. Changing
`placement_version` invalidates stale cache after rebalance.

## Assignment Algorithms

Assignment is used to create or rebalance placement records. Normal reads and
writes should use the stored `PlacementRecord`.

Do not do this on every request:

```text
request -> check live load -> pick any currently light shard
```

Do this instead:

```text
new routing_key -> weighted rendezvous assignment -> PlacementRecord
later requests -> PlacementRecord -> owning shard
```

This keeps shard-local cache useful and prevents the same topic/user from
moving across databases unpredictably.

### Weighted Rendezvous Hashing

Default shard choice algorithm.

```python
def choose_shard(routing_key: str, shards: list[RetrievalShard]) -> RetrievalShard:
    candidates = [s for s in shards if s.state == "active"]
    return max(candidates, key=lambda s: score(routing_key, s))


def score(routing_key: str, shard: RetrievalShard) -> float:
    load_penalty = 1.0 + shard.cpu + (shard.queue_depth / 100.0) + (shard.qps / 1000.0)
    effective_weight = shard.weight / load_penalty
    return stable_hash_float(f"{routing_key}:{shard.shard_id}") * effective_weight
```

Short description: stable assignment with capacity/load awareness. Adding or
removing shards moves fewer keys than modulo hashing.

Stable hash helpers:

```python
import hashlib


def stable_hash_int(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def stable_hash_float(value: str) -> float:
    return stable_hash_int(value) / float(2**64 - 1)
```

Placement creation:

```python
def get_or_create_placement(routing_key: str) -> PlacementRecord:
    existing = placement_registry.get(routing_key)
    if existing and existing.state == "active":
        return existing

    shard = choose_shard(routing_key, shard_registry.active_shards())
    record = PlacementRecord(
        placement_id=new_id(),
        placement_version=placement_registry.next_version(),
        routing_key=routing_key,
        primary_shard_id=shard.shard_id,
        replica_shard_ids=(),
        collection_name=collection_for(routing_key),
        state="active",
    )
    placement_registry.save(record)
    return record
```

### Replica Selection

If replication is enabled, choose the top N shards by rendezvous score.

```python
def choose_placement_shards(
    routing_key: str,
    shards: list[RetrievalShard],
    replication_factor: int,
) -> tuple[RetrievalShard, tuple[RetrievalShard, ...]]:
    candidates = [s for s in shards if s.state == "active"]
    ranked = sorted(
        candidates,
        key=lambda shard: score(routing_key, shard),
        reverse=True,
    )
    selected = ranked[:replication_factor]
    return selected[0], tuple(selected[1:])
```

Read behavior:

```text
1. Read from primary for cache locality.
2. If primary is down, read from the first readable replica.
3. If no readable target exists, return unavailable.
```

Write behavior:

```text
1. Write to primary.
2. Replicate synchronously or asynchronously depending on durability policy.
3. Do not read from replicas unless failover or read-scaling policy allows it.
```

### Project Single

Use for small projects.

```python
routing_key = f"project:{project_id}"
shard = choose_shard(routing_key, active_shards)
```

Pros: simplest and strongest cache locality.

Cons: one large project can overload one shard.

### User Single

Use when queries are usually user-scoped.

```python
routing_key = f"project:{project_id}:user:{user_id}"
shard = choose_shard(routing_key, active_shards)
```

Pros: many users distribute naturally; cache stays warm per user.

Cons: one hot user can overload one shard.

### Topic Single

Use when topics/workspaces/channels are the main query boundary.

```python
routing_key = f"project:{project_id}:topic:{topic_id}"
shard = choose_shard(routing_key, active_shards)
```

Pros: topic cache locality.

Cons: one hot topic can overload one shard.

### User Bucketed

Use when one user's data becomes too large or hot.

```python
base_key = f"project:{project_id}:user:{user_id}"
bucket_id = stable_hash(doc_id) % bucket_count
routing_key = f"{base_key}:bucket:{bucket_id}"
shard = choose_shard(routing_key, active_shards)
```

Ingest targets one bucket. User-scoped search fans out across all user buckets.

### Topic Bucketed

Use when one topic becomes too large or hot.

```python
base_key = f"project:{project_id}:topic:{topic_id}"
bucket_id = stable_hash(doc_id) % bucket_count
routing_key = f"{base_key}:bucket:{bucket_id}"
shard = choose_shard(routing_key, active_shards)
```

Ingest targets one bucket. Topic-scoped search fans out across all topic
buckets.

### Doc Bucketed

Use when a whole project is huge and queries often span users/topics.

```python
bucket_id = stable_hash(doc_id) % bucket_count
routing_key = f"project:{project_id}:doc_bucket:{bucket_id}"
shard = choose_shard(routing_key, active_shards)
```

Pros: best spread for large projects.

Cons: project-wide search fans out across many buckets.

## Routing Key Resolver

Write path:

```python
def write_routing_key(scope: ProjectScope, policy: RoutingPolicy) -> str:
    if policy.routing_mode == "project_single":
        return f"project:{scope.project_id}"

    if policy.routing_mode == "user_single":
        return f"project:{scope.project_id}:user:{scope.user_id}"

    if policy.routing_mode == "topic_single":
        return f"project:{scope.project_id}:topic:{scope.topic_id}"

    if policy.routing_mode == "user_bucketed":
        bucket = stable_hash(scope.doc_id) % policy.bucket_count
        return f"project:{scope.project_id}:user:{scope.user_id}:bucket:{bucket}"

    if policy.routing_mode == "topic_bucketed":
        bucket = stable_hash(scope.doc_id) % policy.bucket_count
        return f"project:{scope.project_id}:topic:{scope.topic_id}:bucket:{bucket}"

    if policy.routing_mode == "doc_bucketed":
        bucket = stable_hash(scope.doc_id) % policy.bucket_count
        return f"project:{scope.project_id}:doc_bucket:{bucket}"

    raise ValueError(f"unknown routing mode: {policy.routing_mode}")
```

Read path:

```python
def read_routing_keys(scope: ProjectScope, policy: RoutingPolicy) -> list[str]:
    if policy.routing_mode == "user_bucketed":
        return [
            f"project:{scope.project_id}:user:{scope.user_id}:bucket:{i}"
            for i in range(policy.bucket_count)
        ]

    if policy.routing_mode == "topic_bucketed":
        return [
            f"project:{scope.project_id}:topic:{scope.topic_id}:bucket:{i}"
            for i in range(policy.bucket_count)
        ]

    if policy.routing_mode == "doc_bucketed":
        return [
            f"project:{scope.project_id}:doc_bucket:{i}"
            for i in range(policy.bucket_count)
        ]

    return [write_routing_key(scope, policy)]
```

## Placement Resolver

```python
def resolve_write(scope: ProjectScope, policy: RoutingPolicy) -> PlacementPlan:
    key = write_routing_key(scope, policy)
    record = placement_registry.get_or_create(key)
    return PlacementPlan(
        placement_version=record.placement_version,
        targets=(target_from_record(record),),
        fanout=False,
    )


def resolve_read(scope: ProjectScope, policy: RoutingPolicy) -> PlacementPlan:
    keys = read_routing_keys(scope, policy)
    records = [placement_registry.get_required(key) for key in keys]
    return PlacementPlan(
        placement_version=max(r.placement_version for r in records),
        targets=tuple(target_from_record(r) for r in records),
        fanout=len(records) > 1,
    )
```

Short description: write resolves to one target; bucketed read resolves to many
targets and requires result merge.

## Request Examples

### Ingest With Placement

```json
{
  "request_id": "ing-1",
  "project_scope": {
    "project_id": "real-estate",
    "user_id": "user-42",
    "topic_id": "rentals",
    "doc_id": "house-123"
  },
  "placement": {
    "placement_version": 4,
    "targets": [
      {
        "routing_key": "project:real-estate:topic:rentals:bucket:17",
        "shard_id": "retrieval-03",
        "collection_name": "rag_real-estate_v1"
      }
    ]
  }
}
```

### Search With Placement

```json
{
  "request_id": "search-1",
  "project_scope": {
    "project_id": "real-estate",
    "user_id": "user-42",
    "topic_id": "rentals"
  },
  "query_text": "two bedroom near subway",
  "placement": {
    "placement_version": 4,
    "fanout": true,
    "targets": [
      {"routing_key": "project:real-estate:topic:rentals:bucket:0", "shard_id": "retrieval-01", "collection_name": "rag_real-estate_v1"},
      {"routing_key": "project:real-estate:topic:rentals:bucket:1", "shard_id": "retrieval-02", "collection_name": "rag_real-estate_v1"},
      {"routing_key": "project:real-estate:topic:rentals:bucket:2", "shard_id": "retrieval-03", "collection_name": "rag_real-estate_v1"}
    ]
  }
}
```

## Search Fanout And Merge

When a placement plan has multiple targets:

```text
1. Send the query to each target shard.
2. Each shard checks its local cache.
3. Each shard returns top candidates.
4. Retrieval router merges by normalized score.
5. Apply final top_k and return one response.
```

Merge structure:

```python
@dataclass(frozen=True)
class ShardSearchResult:
    shard_id: str
    routing_key: str
    chunks: list[dict]
    elapsed_ms: int
    cache_hit: bool
```

## Rebalancing

Rebalancing changes ownership deliberately; it should not happen per request.

Hot-key split:

```text
1. Detect hot project/user/topic key.
2. Change routing policy to bucketed mode or increase bucket_count.
3. Create new placement records with a higher placement_version.
4. Route new writes to new buckets.
5. Reindex old data from remote storage or migrate vectors.
6. Expire old cache namespace by placement_version.
```

Placement states:

```text
active: normal read/write target
moving: writes use new version; old data is being migrated
draining: readable during migration, no new writes
stale: old placement version; not used for normal routing
```

Shard states:

```text
active: can receive new placements, reads, and writes
readonly: can serve reads, no new writes
draining: no new placements; existing data migrates away
down: not used except replica failover decisions
```

Shard drain:

```text
1. Mark shard state as draining.
2. Stop assigning new placements to it.
3. Move its placement records to active shards.
4. Reindex/migrate data.
5. Mark old placements stale.
```

## Minimal Tables

Routing policy table:

```sql
CREATE TABLE retrieval_routing_policies (
    project_id TEXT PRIMARY KEY,
    routing_mode TEXT NOT NULL,
    bucket_count INTEGER NOT NULL,
    replication_factor INTEGER NOT NULL,
    read_fanout TEXT NOT NULL,
    updated_at REAL NOT NULL
);
```

Shard registry:

```sql
CREATE TABLE retrieval_shards (
    shard_id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    qdrant_endpoint TEXT NOT NULL,
    weight INTEGER NOT NULL,
    state TEXT NOT NULL,
    qps REAL NOT NULL,
    queue_depth INTEGER NOT NULL,
    cpu REAL NOT NULL,
    memory REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

Current SQLite implementation stores the same serving fields and omits
`updated_at` until lifecycle/audit timestamps are wired.

Placement registry:

```sql
CREATE TABLE retrieval_placements (
    routing_key TEXT PRIMARY KEY,
    placement_id TEXT NOT NULL,
    placement_version INTEGER NOT NULL,
    primary_shard_id TEXT NOT NULL,
    replica_shard_ids_json TEXT NOT NULL,
    collection_name TEXT NOT NULL,
    state TEXT NOT NULL,
    updated_at REAL NOT NULL
);
```

Current SQLite implementation uses `(routing_key, collection_name)` as the
primary key so the same routing key can be reused across collection versions,
and omits `updated_at` until placement lifecycle timestamps are wired.

## Recommended Defaults

Start simple:

```text
small project: project_single
many independent users: user_single
topic-centric application: topic_single
hot user: user_bucketed
hot topic: topic_bucketed
very large project: doc_bucketed
```

Practical first implementation:

```text
1. Add RetrievalShard and PlacementRecord registries.
2. Add weighted rendezvous assignment for new routing keys.
3. Start with project_single or topic_single.
4. Add bucketed modes only when a project/user/topic becomes hot.
5. Put placement_version in cache keys and request messages.
```

Short summary:

```text
ProjectScope gives business identity.
RoutingPolicy decides key granularity.
RoutingKey is the stable hash input.
PlacementRecord maps key to database shard.
PlacementPlan tells retrieval where to execute.
CacheScope keeps cache local to the owning shard.
```
