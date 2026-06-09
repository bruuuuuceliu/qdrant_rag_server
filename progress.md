# Information Retrieval Service Implementation Progress

**Reviewed**: 2026-06-09
**Status**: Prototype / core scaffold, not production complete

## Summary

The project has a useful async information-retrieval scaffold: core models,
project adapters, gateway validation, Qdrant dense retrieval, Qdrant sparse
BM25-style retrieval, hybrid retrieval, ingestion workers, optional reranking,
caching, object storage abstractions, gRPC transport, health checks, and
embedding-version management.

It should still be treated as a prototype. The retrieval direction is now
clearer and more capable, but the next work should keep the system minimal,
replaceable, and retrieval-first rather than expanding into a full platform.

## Current Phase Status

| Area | Current status | Notes |
|---|---|---|
| Core models | Implemented scaffold | `project_id`, `user_id`, default `kb_id`, `doc_id`, chunks, payloads, filters, `data_type`, `visibility`, `content_hash`, `embedding_version`, and `chunker_version` exist. |
| Project adapters | Implemented scaffold | Adapter interface is good. `WebsiteProjectAdapter` still returns hard-coded config values such as `example.com`. |
| Config repository | Implemented scaffold | SQLite stores base config fields. It does not yet store adapter-specific config such as website domains. |
| Gateway | Implemented scaffold | Rejects raw filters, builds server-side scope, and normalizes missing/blank ingest `kb_id` to the default KB. Current limiter covers plan preparation, not full engine work. |
| Qdrant vector store | Implemented scaffold | Dense collection lifecycle, dense upsert/search, scoped delete, hybrid dense+sparse collection creation, hybrid upsert, and sparse search are implemented. Point IDs are deterministic and scoped. |
| Retrieval methods | Implemented scaffold | Dense, BM25-style sparse retrieval, and hybrid retrieval are implemented behind retriever interfaces. Sparse retrieval uses Qdrant named sparse vectors, not a SQLite FTS sidecar. |
| Search engine | Implemented scaffold | Embeds dense queries when needed, sparse-encodes BM25 queries when needed, selects dense/BM25/hybrid retrievers, optionally boosts entities, optionally reranks, caches results, and reports `elapsed_ms`. No engine-level search semaphore yet. |
| Ingestion | Implemented scaffold | Background workers and in-memory status exist. Hybrid ingest writes dense and sparse vectors to the same Qdrant point. Jobs are not durable and the queue is unbounded. |
| NER | Implemented scaffold | Optional local NER extractor protocol and metadata serialization exist. Entity boost can be applied after retrieval. Local spaCy dependency remains optional. |
| Object storage | Implemented scaffold | Memory, filesystem, and S3-compatible adapters exist. Raw content is stored only if `metadata["raw_text"]` exists. |
| Cache | Implemented scaffold | Tier-1 memory cache and Tier-2 SQLite response cache exist. Search cache keys now include retrieval mode, sparse vector name, sparse encoder settings, and NER settings. Response cache key should still include broader model/generation config. |
| Generation | Experimental | gRPC `Generate` exists, but the core system should stay retrieval-first for now. The engine does not use adapter prompt builders in this path. App wiring is opt-in and returns a clear disabled response when generation is unavailable. |
| Versioning | Partial | Embedding collection version manager exists. Document/corpus conflict/version control is not implemented. Sparse index version is part of retrieval settings/cache fingerprint, but full sparse index migration/version management is not implemented. |
| Health/metrics | Implemented scaffold | Component availability and in-memory counters exist. Not a full observability layer. |
| gRPC | Implemented scaffold | Unary `Search`, `Ingest`, `GetIngestJobStatus`, `Generate`, and `HealthCheck` exist. Proto lacks explicit raw content and `data_type`. |
| Tests | Useful but mostly mocked | Current suite covers Qdrant point IDs, scoped delete, default KB behavior, vector validation, storage, generation, health, e2e scaffolding, dense/BM25/hybrid retrieval config, sparse Qdrant wiring, hybrid fusion, and hybrid ingest. Need live Qdrant sparse integration tests, durable ingest job tests, raw storage flow tests, queue saturation tests, and async DB behavior tests. |
| Documentation | Improved | `docs/implementations/` now documents Qdrant sparse retrieval, runtime retrieval configuration, tests, and showcase usage. |

## Recently Completed

- Added `Retriever` contracts and dense/BM25/hybrid retriever implementations.
- Added Qdrant sparse BM25-style retrieval using named sparse vectors.
- Added `SparseTextEncoder` and lazy `FastEmbedSparseTextEncoder`.
- Added Qdrant hybrid collection creation, hybrid point upsert, and sparse search.
- Updated `RagEngine` to encode dense and sparse vectors according to retrieval mode.
- Updated retrieval config parsing for `dense`, `bm25`, and `hybrid`.
- Updated search cache fingerprint for sparse retrieval settings.
- Removed the SQLite FTS5 BM25 sidecar design from the active retrieval plan.
- Added a full-document dense/BM25/hybrid showcase.
- Added formal implementation docs under `docs/implementations/`.

## Verified Behavior

Latest local verification during the sparse retrieval update:

```bash
python -m pytest tests/test_sparse_retrieval.py -q
python -m pytest -q
python -m py_compile examples/unites/rag_multi_retrieval_showcase.py
git diff --check
```

Observed results:

```text
tests/test_sparse_retrieval.py: 7 passed
full test suite: 152 passed
```

The sparse retrieval tests use fake Qdrant and fake sparse encoders. They verify
wiring and contracts. Live ranking behavior still needs integration testing
against a real Qdrant instance with sparse vectors enabled.

## Reliable Enough To Keep

- The two-project structure is now clearer:
  - `retrieval_service` owns low-level retrieval primitives and services.
  - `project_service` owns project-aware orchestration and policy.
- `ProjectAdapter` boundary is still the strongest design element.
- Gateway-side scope construction is the right data isolation direction.
- Default KB behavior keeps the minimal path simple while still allowing explicit KB partitioning.
- Query-time retrieval uses Qdrant payload text instead of remote object storage.
- Dense, sparse, and hybrid retrieval now share retriever interfaces.
- Cache, storage, reranker, generation, versioning, and health are separated as services.
- Tests are organized and useful as a scaffold.

## Must Fix Before Calling This Production-Ready

1. **Live Qdrant sparse integration tests**

   The sparse retrieval unit tests mock Qdrant. Add optional integration tests
   that create a hybrid collection, insert dense+sparse points, and run real
   dense, sparse, and hybrid searches.

2. **Collection migration and versioning**

   Existing dense-only collections need a clear migration or reingest path
   before `bm25` or `hybrid` mode is enabled. Sparse vector slot validation
   should produce clear startup/search errors.

3. **Complete optional app wiring**

   `create_app()` now wires embedding, metrics, health, generation, sparse
   encoder, Qdrant sparse BM25 index, and NER. It still needs optional wiring
   for reranker, object storage, and version manager.

4. **Async-safe local persistence**

   SQLite config/cache/versioning and filesystem object storage still run
   blocking work inside async methods. Use `aiosqlite` or a shared
   executor-backed DB runner.

5. **Durable, replaceable ingest jobs**

   `RagEngine` keeps `_ingest_status` in memory and uses an unbounded
   `asyncio.Queue`. Job status disappears on restart and failed errors are not
   stored in a durable record.

6. **Explicit raw content**

   Raw object storage currently depends on `document.metadata.get("raw_text")`.
   Raw content should be a first-class ingest input and the resulting
   `raw_storage_key` should be saved with the job or document record.

7. **Data-type registry**

   Different data types should be able to define schema, parsing, chunking,
   payload fields, retrieval filters, and default retrievers without abusing
   generic metadata.

8. **Config-backed adapter behavior**

   `WebsiteProjectAdapter.get_config()` currently returns hard-coded domains
   and model names. Website domains and other adapter settings should come from
   project config.

9. **Engine-level resource limits**

   Gateway concurrency limits only wrap plan preparation. Search, embedding,
   sparse encoding, Qdrant calls, reranking, and ingestion need simple
   engine-level semaphores and a bounded ingest queue.

10. **Import boundaries**

    Lightweight imports of models/config/cache should not require optional
    runtime dependencies. Sparse FastEmbed loading is lazy, but the wider import
    boundary should continue to be checked.

## Recommended Next Milestone

```text
Minimal safe hybrid information retrieval core:
project/user-scoped ingest, dense/sparse/hybrid search, delete, cache
invalidation, raw backup, and durable job status.
```

Do not expand into organization-level tenancy, distributed queues, advanced
auth, or full observability until the safety fixes above are complete.

## Current Code Structure

```text
qdrant_rag_server/
  configs/
    config.py
    retrieval/config.py
  project_service/
    adapters/
    config/
    gateway/
    rag/
      engine.py
      retrieval_config.py
      retriever_factory.py
      cache_keys.py
      entity_boost.py
      filters.py
    schemas/
    server/
    versioning/
  retrieval_service/
    core/
    embedding/
    health/
    llm/
    services/
      bm25.py
      hybrid.py
      retriever.py
      sparse_encoder.py
      vector_store.py
      cache.py
    storage/
  server/
    app.py
  docs/
    implementations/
  examples/
    unites/rag_multi_retrieval_showcase.py
  tests/
    test_sparse_retrieval.py
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

Avoid percentage-complete claims until the minimal safe core has real safety
tests and can run against the declared dependencies.
