# Implementation Roadmap

This roadmap tracks the current broker-first service split.

## Implemented

- Manager publishes authenticated task-intake envelopes to Redpanda-compatible
  topics.
- Task manager consumes task intake, publishes normalized task requests, and
  writes Redis task status from task events/results.
- Task service consumes task requests, asks project service for planning, sends
  helper commands, fans in helper results, and publishes task events/results.
- Project service owns project config, adapters, scope construction, placement
  planning, and project-document planning.
- Ingestion helper owns source loading, parsing, chunking, ingestion job
  records, and neutral prepared-content results.
- Retrieval helper owns search/delete/raw-document work.
- Retrieval index helper owns embedding, sparse encoding, NER enrichment, and
  Qdrant indexing.
- Workflow log service owns audit/domain command handling and durable log
  storage.
- Local runner starts the same broker-first topology with Redpanda, Redis,
  Qdrant, task services, domain services, helper workers, storage, SQLite node,
  and manager gRPC.
- Placement execution and local placement registry are implemented for indexing,
  search, delete, cache namespacing, and primary/replica target resolution.
- Config profile variants and component env examples live under `configs/`.
- Generated compatibility gRPC stubs live under
  `shared.transport.grpc.generated`, outside service-owned packages.

## Current Compatibility Boundary

- The public compatibility `RagService` gRPC API remains at the manager edge.
- Generated protobuf stubs live under the neutral
  `shared.transport.grpc.generated` namespace.
- `Generate` is not part of the broker-first manager flow and returns
  `UNIMPLEMENTED`.

## Removed Runtime Paths

The current design no longer supports:

- embedded/local manager runtime composition
- in-memory or SQLite queue brokers as service communication transports
- direct manager-to-project client modes
- direct project/RAG gRPC sidecar mode
- retrieval direct HTTP/API or local queue transports outside Redpanda helper
  command flow
- root `server` compatibility package

## Next Work

- Continue tightening import-boundary tests around service-owned modules and the
  manager gRPC compatibility adapter.
- Add production-grade retry, lease/claim timeout, attempt-count, backoff, and
  dead-letter behavior.
- Add multi-endpoint placement smoke coverage and migration/reindex
  orchestration.
- Split tests further by service ownership and runtime surface.
