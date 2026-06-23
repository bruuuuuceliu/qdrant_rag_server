# Retrieval Placement Execution

Status: accepted.

## Context

Placement plans already flowed through project planning, queued ingestion,
retrieval search/delete contracts, and retrieval indexing commands. The missing
runtime step was using those plans to select Qdrant stores and collections.

## Decision

Retrieval services now execute placement plans locally:

- `PlacementStoreResolver` maps placement shard IDs to Qdrant stores using the
  retrieval shard registry, with the configured store as fallback.
- `SQLitePlacementRegistry` persists shard records, per-project/default routing
  policies, and versioned placement records.
- `PlacementResolver` can resolve policies by project, save policies, and run
  explicit rebalance state transitions from active to moving/stale/active
  records.
- `IndexingService` writes prepared chunks to the placement write set: primary
  plus replica targets.
- `RetrievalService.search` groups placement read targets by routing key,
  searches one target per group, falls back from primary to replicas on target
  failure, and merges hits by score.
- `RetrievalService.delete_document` deletes dense and sparse records from the
  placement write set.
- Search cache keys include placement version, shard ID, and routing key.
- Resolver-owned stores are closed through retrieval and indexing service
  shutdown hooks.

## Still Pending

- Migration/reindex orchestration that copies data before replacement
  placements are activated.
- Production broker retry, lease, and dead-letter semantics.
- Integration smoke tests against multiple live Qdrant endpoints.
