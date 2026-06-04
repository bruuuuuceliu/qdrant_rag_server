# RAG Service Development Plan

## Purpose

This plan breaks the RAG service implementation into phases. The goal is to build the reusable project-based core first, then add website-specific behavior as one adapter implementation.

## Guiding Principles

- Build async APIs from the first phase.
- Keep the engine dependent on base models and adapter interfaces only.
- Keep project-specific schemas and rules in child adapters.
- Enforce `project_id` and `user_id` isolation at the gateway.
- Keep OpenRouter API keys request-scoped.
- Store raw documents in remote storage, but never read remote storage at query time.
- Prefer small, testable components with focused integration tests.

## Phase 1: Core Models and Configuration

Deliverables:

- Define base model classes:
  - `BaseProjectConfig`
  - `BaseQueryScope`
  - `BaseRetrievalFilter`
  - `BaseDocument`
  - `BaseChunk`
  - `BaseChunkPayload`
  - `BaseIngestJob`
  - `BaseCacheScope`
- Define the `ProjectAdapter` interface.
- Define a project adapter registry.
- Create SQLite config schema for:
  - projects
  - active embedding versions
  - project type mappings
  - chunker config
  - retrieval config
  - cache config
- Add config repository APIs.

Acceptance criteria:

- A project can be registered with `project_id`, `project_type`, and active embedding version.
- The gateway can resolve a `ProjectAdapter` from `project_id`.
- Unit tests cover base model validation and adapter registry behavior.

## Phase 2: Async Gateway Skeleton

Deliverables:

- Create async gRPC service skeleton.
- Add request validation.
- Add enforced construction of `BaseQueryScope`.
- Add enforced construction of `BaseRetrievalFilter`.
- Add per-project and per-user concurrency controls.
- Add structured error responses for invalid scope, missing project, missing adapter, and saturation.

Acceptance criteria:

- Gateway accepts search and ingest requests asynchronously.
- Clients cannot submit raw Qdrant filters directly.
- Missing or invalid `project_id` and `user_id` requests are rejected.
- Concurrency limit behavior is covered by tests.

## Phase 3: Embedding, Qdrant, and Retrieval

Deliverables:

- Load BGE-base embedding model once at engine startup.
- Add async-safe embedding service wrapper.
- Add Qdrant collection naming and lifecycle helpers:
  - `rag_{project_id}_{embedding_version}`
- Add Qdrant upsert support for `BaseChunkPayload`.
- Add Qdrant search with enforced `BaseRetrievalFilter`.
- Add top-k retrieval configuration.

Acceptance criteria:

- Documents can be embedded and upserted into the correct project collection.
- Queries search only the allowed project and user scope.
- Shared project content with `user_id = "__shared__"` can be included when requested.
- Integration tests prove cross-project and cross-user isolation.

## Phase 4: Reranking

Deliverables:

- Load BGE-Reranker-base once at engine startup.
- Add async-safe reranker service wrapper.
- Retrieve top 20 candidates from Qdrant.
- Return top 5 reranked chunks by default.
- Make candidate count and final count configurable by project.

Acceptance criteria:

- Reranking runs without blocking unrelated requests.
- Retrieval returns deterministic top chunk structure.
- Unit tests cover reranking configuration and fallback behavior.

## Phase 5: Ingestion Pipeline

Deliverables:

- Implement async ingestion endpoint.
- Implement ingest job tracking.
- Store raw documents in remote storage.
- Parse documents through `ProjectAdapter`.
- Build chunks through `ProjectAdapter`.
- Build Qdrant payloads through `ProjectAdapter`.
- Upsert chunks into Qdrant.
- Invalidate affected caches after successful upsert.

Acceptance criteria:

- Multiple ingestion jobs can run concurrently.
- Uploads can return a job ID for background processing.
- Failed jobs record status and error.
- Query-time retrieval does not fetch from remote storage.
- Tests cover cache invalidation after document upload and delete.

## Phase 6: Website Project Adapter

Deliverables:

- Implement `WebsiteProjectConfig`.
- Implement `WebsiteDocument`.
- Implement `WebsiteChunkPayload`.
- Implement `WebsiteProjectAdapter`.
- Add domain validation.
- Add URL, canonical URL, title, description, and section metadata handling.
- Add website-specific prompt builder.

Acceptance criteria:

- Website documents map into base documents and website payloads.
- Website-specific fields are added only inside the adapter.
- Core engine code does not branch on website-specific fields.
- Tests cover valid domain ingestion, invalid domain rejection, and website prompt construction.

## Phase 7: Cache Implementation

Deliverables:

- Implement Tier 1 in-memory retrieval cache:
  - per-project `OrderedDict`
  - 5,000 entries per project
  - 1 hour TTL
  - concurrency-safe access
- Implement Tier 2 SQLite response cache:
  - scoped by `project_id` and `user_id`
  - 1 hour TTL
  - survives restart
- Add invalidation APIs:
  - clear project
  - clear user
  - clear expired

Acceptance criteria:

- Tier 1 cache returns repeated retrieval results before TTL expiry.
- Tier 2 cache returns repeated LLM responses before TTL expiry.
- Document upload or delete clears Tier 1 for the project and Tier 2 for the user.
- Config changes clear both tiers for the project.
- Tests cover concurrent cache read, write, and invalidation.

## Phase 8: OpenRouter Generation Path

Deliverables:

- Add request model field for OpenRouter API key.
- Validate that generation requests include an OpenRouter key.
- Call OpenRouter using only the request-provided key.
- Prevent the key from appearing in logs, cache keys, cached responses, Qdrant payloads, or SQLite records.
- Add response caching after generation.

Acceptance criteria:

- Requests without an OpenRouter key fail when generation is required.
- Requests with different keys can run concurrently.
- No cache or database record stores the key.
- Tests cover key redaction and cache key construction.

## Phase 9: Versioning and Re-Indexing

Deliverables:

- Add collection creation for new embedding or chunker versions.
- Add background re-index job from remote storage.
- Add atomic active version swap in `config.db`.
- Add old collection grace-period tracking.
- Add old collection deletion after 7 days.

Acceptance criteria:

- Queries continue using the old active version during re-indexing.
- Atomic swap changes query traffic to the new collection.
- Old collections remain available during the grace period.
- Re-index status is visible through job tracking.

## Phase 10: Recovery and Operations

Deliverables:

- Add Qdrant snapshot process.
- Add snapshot restore script or runbook.
- Add off-site snapshot upload/download process.
- Add full rebuild job from raw documents.
- Add health checks for:
  - gateway
  - Qdrant
  - embedding model
  - reranker model
  - config database
  - response cache
- Add metrics for latency, cache hit rate, queue depth, saturation, and ingestion status.

Acceptance criteria:

- Same-machine Qdrant restart recovery is documented and tested.
- New-machine snapshot restore is documented.
- Full rebuild can run in the background.
- Health checks fail clearly when dependencies are unavailable.

## Phase 11: End-to-End Testing

Deliverables:

- End-to-end ingest and query tests.
- Multi-project isolation tests.
- Multi-user isolation tests.
- Shared content tests.
- Concurrent query tests.
- Concurrent ingestion tests.
- Ingestion while querying tests.
- Cache invalidation tests.
- Request-scoped OpenRouter key tests.

Acceptance criteria:

- Full ingest-to-query flow works for website projects.
- A user cannot retrieve another user's private chunks.
- A project cannot retrieve another project's chunks.
- Shared project content is included only when allowed.
- Concurrent workloads complete without corrupting caches or filters.

## Initial Implementation Order

1. Core base models and adapter registry.
2. Async gateway skeleton.
3. Config database schema and repositories.
4. Qdrant collection helpers and retrieval filters.
5. Embedding wrapper.
6. Basic ingestion and upsert.
7. Basic retrieval.
8. Website adapter.
9. Reranker.
10. Tier 1 and Tier 2 caches.
11. OpenRouter generation path.
12. Versioning and recovery features.

## Open Questions

- Should document parsing happen entirely in FaaS, entirely in the engine, or split by file type?
- Should uploads always return a job ID, or should small uploads wait for completion?
- What is the maximum allowed document size per project?
- What project types should be supported after website RAG?
- Should cache TTLs be global defaults or fully project-specific?
- What auth layer owns validation of `project_id` and `user_id` membership?
