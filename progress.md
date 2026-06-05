# Information Retrieval Service Implementation Progress

**Reviewed**: 2026-06-05  
**Status**: Prototype / core scaffold, not production complete

## Summary

The project has a useful async information-retrieval scaffold: core models, project adapters, gateway validation, Qdrant vector search, ingestion workers, optional reranking, caching, object storage abstractions, gRPC transport, health checks, and embedding-version management.

However, it should still be treated as a prototype. The core direction is good, but the next work should keep it minimal, replaceable, and retrieval-first rather than expanding into a full RAG or platform system.

## Current Phase Status

| Area | Current status | Notes |
|---|---|---|
| Core models | Implemented scaffold | `project_id`, `user_id`, default `kb_id`, `doc_id`, chunks, payloads, filters, `data_type`, `visibility`, `content_hash`, `embedding_version`, and `chunker_version` exist. |
| Project adapters | Implemented scaffold | Adapter interface is good. `WebsiteProjectAdapter` still returns hard-coded config values such as `example.com`. |
| Config repository | Implemented scaffold | SQLite stores base config fields. It does not yet store adapter-specific config such as website domains. |
| Gateway | Implemented scaffold | Rejects raw filters, builds server-side scope, and normalizes missing/blank ingest `kb_id` to the default KB. Current limiter covers plan preparation, not full engine work. |
| Qdrant vector store | Implemented scaffold | Collection lifecycle, upsert, search, and delete exist. Point IDs are deterministic and scoped; document delete filters by project, user, KB, and doc. |
| Search engine | Implemented scaffold | Embeds query, searches Qdrant, optionally reranks, caches results, and reports `elapsed_ms`. No engine-level search semaphore yet. |
| Ingestion | Implemented scaffold | Background workers and in-memory status exist. In-memory records include `doc_id`, errors, and timestamps. Jobs are not durable and queue is unbounded. |
| Object storage | Implemented scaffold | Memory, filesystem, and S3-compatible adapters exist. Raw content is stored only if `metadata["raw_text"]` exists. |
| Cache | Implemented scaffold | Tier-1 memory cache and Tier-2 SQLite response cache exist. Response cache key should include model/generation config. |
| Retrieval methods | Early scaffold | Vector retrieval exists. BM25/hybrid retrieval needs a retriever interface and coordinator before this becomes a general information retrieval service. |
| Generation | Experimental | gRPC `Generate` exists, but the core system should stay retrieval-first for now. The engine does not use adapter prompt builders in this path. App wiring is opt-in and returns a clear disabled response when generation is unavailable. |
| Versioning | Partial | Embedding collection version manager exists. Document/corpus conflict/version control is not implemented. |
| Health/metrics | Implemented scaffold | Component availability and in-memory counters exist. Not a full observability layer. |
| gRPC | Implemented scaffold | Unary `Search`, `Ingest`, `GetIngestJobStatus`, `Generate`, and `HealthCheck` exist. Proto lacks explicit raw content and `data_type`. |
| Tests | Useful but mostly mocked | Phase tests provide coverage scaffolding. Current suite covers Qdrant point IDs, scoped delete, default KB behavior, vector validation, storage, generation, health, and e2e scaffolding. Need stronger integration tests for durable ingest jobs, raw storage flow, queue saturation, async DB behavior, and retrieval coordination. |

## Reliable Enough To Keep

- Folder structure under `rag_server/` is reasonable.
- `ProjectAdapter` boundary is the strongest design element.
- Gateway-side scope construction is the right data isolation direction.
- Default KB behavior keeps the minimal path simple while still allowing explicit KB partitioning.
- Query-time retrieval uses Qdrant payload text instead of remote object storage.
- Cache, storage, reranker, generation, versioning, and health are correctly separated as services.
- Tests are organized by phase and are useful as a scaffold.

## Must Fix Before Calling This Production-Ready

1. **Complete optional app wiring**

   `create_app()` now uses a real embedding provider object and wires metrics, health, and opt-in generation. It still needs optional wiring for reranker, object storage, and version manager.

2. **Async-safe local persistence**

   SQLite config/cache/versioning and filesystem object storage still run blocking work inside async methods. Use `aiosqlite` or a shared executor-backed DB runner.

3. **Durable, replaceable ingest jobs**

   `RagEngine` keeps `_ingest_status` in memory and uses an unbounded `asyncio.Queue`. Job status disappears on restart and failed errors are not stored in a durable record.

4. **Explicit raw content**

   Raw object storage currently depends on `document.metadata.get("raw_text")`. Raw content should be a first-class ingest input and the resulting `raw_storage_key` should be saved with the job or document record.

5. **General retrieval framework**

   Vector retrieval should move behind a `Retriever` protocol and coordinator so BM25, hybrid retrieval, metadata lookup, and reranking can be added without changing the engine core.

6. **Data-type registry**

   Different data types should be able to define schema, parsing, chunking, payload fields, retrieval filters, and default retrievers without abusing generic metadata.

7. **Config-backed adapter behavior**

   `WebsiteProjectAdapter.get_config()` currently returns hard-coded domains and model names. Website domains and other adapter settings should come from project config.

8. **Engine-level resource limits**

   Gateway concurrency limits only wrap plan preparation. Search, embedding, Qdrant calls, reranking, and ingestion need simple engine-level semaphores and a bounded ingest queue.

9. **Import boundaries**

   `rag_server/__init__.py` eagerly imports Qdrant, embedding, reranking, generation, storage, and versioning modules. Lightweight imports of models/config/cache should not require optional runtime dependencies.

## Recommended Next Milestone

```text
Minimal safe information retrieval core:
project/user-scoped ingest, search, delete, cache invalidation, and raw backup.
```

Do not expand into organization-level tenancy, distributed queues, advanced auth, or full observability until the safety fixes above are complete. Hybrid/BM25 work should be added only through a small retriever abstraction, not as a second hard-coded engine path.

## Current Code Structure

```text
qdrant_rag_server/
  proto/rag_service.proto
  rag_server/
    adapters/base.py
    adapters/website.py
    config/repository.py
    core/models.py
    engine/engine.py
    gateway/handler.py
    grpc/server.py
    health/health.py
    services/cache.py
    services/embedding.py
    services/generation.py
    services/reranker.py
    services/vector_store.py
    storage/base.py
    storage/filesystem.py
    storage/memory.py
    storage/s3.py
    versioning/manager.py
  tests/
    test_phase1_core.py
    test_phase2_gateway.py
    test_phase3_engine.py
    test_phase4_reranker.py
    test_phase5_ingestion.py
    test_phase6_website_adapter.py
    test_phase7_cache.py
    test_phase8_generation.py
    test_phase9_versioning.py
    test_phase10_health.py
    test_phase11_e2e.py
```

## Documentation Policy

Status documents should distinguish:

- implemented scaffold
- locally verified behavior
- mocked unit coverage
- production-ready behavior
- future extension points

Avoid percentage-complete claims until the minimal safe core has real safety tests and can run against the declared dependencies.
