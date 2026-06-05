# RAG Server Minimalist Critique

Evaluated on: 2026-06-04  
Repository: `qdrant_rag_server`

## Executive Summary

This project has a solid seed: an async RAG server with project adapters, Qdrant retrieval, ingestion, reranking, caches, object storage, and gRPC boundaries. The main idea is right: keep retrieval local and fast, keep raw documents in remote storage for safety, and isolate project/user data through server-built filters.

The main issue is that the current implementation tries to look complete across too many areas. It has many production-shaped pieces, but several are shallow. The project should not become a large platform yet. It should become a small, reliable RAG core.

The best next direction is minimalism:

- Keep the core data model small.
- Fix clear data safety bugs.
- Make ingestion reliable enough to recover from simple failures.
- Keep remote storage as a durable backing source, not a query dependency.
- Keep advanced auth, multi-region recovery, complex service namespaces, and large-scale operations as extension points for later.

## Environment Notes

Commands should be run inside the `evo` conda environment:

```bash
source /home/bruce/miniconda3/etc/profile.d/conda.sh
conda activate evo
```

I checked the environment:

```text
Python 3.12.13
```

I attempted to run the tests in `evo`:

```bash
pytest -q
python -m pytest -q
```

The earlier default environment did not have `pytest`. In `evo`, pytest is available, but collection currently fails because `qdrant_client` is missing:

```text
ModuleNotFoundError: No module named 'qdrant_client'
```

This is not only a dependency issue. It also shows a structure issue: `rag_server/__init__.py` eagerly imports Qdrant-dependent modules, so tests for unrelated areas can fail before they reach the code they actually test.

Minimal fix:

- install project dependencies in `evo`
- reduce eager imports in `rag_server/__init__.py`
- keep heavyweight or optional dependencies imported in their leaf modules

So this report is based on source review plus partial test collection, not a clean locally verified test run.

## What This Project Should Be

A small RAG engine that provides:

- project-based retrieval
- user-scoped private data
- optional project-shared data
- document ingestion
- text-first records for different data types
- local Qdrant search
- optional reranking
- object storage backup for raw documents
- simple response/retrieval caching
- project adapters for different content shapes

It should not yet try to be:

- a full authorization platform
- a complex multi-organization data governance system
- a distributed job processor
- a full observability stack
- a general document management system
- a large workflow engine

Leave hooks for those later, but do not build them now.

## Text-First Extensibility

The project can support other data types, such as running records, user preferences, agent memories, logs, or activity history, as long as the stored RAG representation is text.

The rule should be:

```text
source object -> adapter -> text chunks + metadata -> Qdrant payload
```

For example, a running record can become:

```text
User ran 5.2 km on 2026-06-04 in 28 minutes. Average pace was 5:23/km.
```

with metadata:

```text
data_type=running_record
date=2026-06-04
distance_km=5.2
duration_seconds=1680
```

The RAG server does not need to become structured storage. It only needs to store searchable text plus enough metadata for safe filtering and source tracing.

Minimal structural requirement:

- `BaseDocument`, `BaseChunk`, and `BaseChunkPayload` should remain generic.
- Add a simple `data_type` field.
- Keep `metadata` flexible.
- Let adapters convert each source type into text.
- The engine should not branch on `data_type`.

This is enough to leave room for many future record types without adding a large schema system.

## The Good

### The Architecture Has the Right Core

The project correctly separates:

- core models
- project adapters
- gateway validation
- retrieval engine
- vector store
- embedding/reranking services
- cache
- object storage
- gRPC transport

That is a good modular layout for a small RAG server.

### Project Adapters Are Worth Keeping

The adapter interface is the best design choice in the repo. It lets the engine stay generic while website/documentation/memory/preference behavior can evolve separately.

Keep this idea. Do not replace it with one giant generic pipeline full of conditionals.

### Query-Time Remote Storage Is Avoided

This is important. Remote storage should be for raw document durability and rebuilds. Query-time text should come from Qdrant payloads. The project already follows this general rule.

### Server-Built Retrieval Filters Exist

The gateway rejects client-supplied raw filters, and the engine builds Qdrant filters from structured scope. This is the right baseline for data isolation.

### The Test Structure Is Useful

The phase-based tests are a good scaffold, even if they currently rely too much on mocks.

## The Bad

## 1. The Project Claims Too Much Completion

`progress.md` says nearly everything is implemented. That is not accurate. The repo has scaffolding for many things, not production-ready versions of those things.

This should be corrected because inaccurate status encourages bad planning.

Minimal fix:

- mark the project as "prototype / core scaffold"
- list what is actually reliable
- list what is intentionally future work

## 2. Tenant Safety Has Concrete Bugs

The current payload model includes `project_id`, `user_id`, `kb_id`, and `doc_id`, which is enough for a small first version.

But two implementation details are unsafe:

- Qdrant point IDs use `chunk_id` alone.
- Document delete filters by `doc_id` alone.

Since a collection is per project, two users in the same project can collide if they use the same `doc_id` or chunk IDs.

Minimal fix:

- Make point IDs include `project_id`, `user_id`, `kb_id`, `doc_id`, and `chunk_index`.
- Delete by `project_id`, `user_id`, `kb_id`, and `doc_id`.

Do not expand into a large org/service/namespace model yet. The current project/user/KB model is acceptable if the implementation enforces it correctly.

For extensibility, add `data_type` but keep it simple. It should be a payload/filter field, not a reason for the engine to branch into different logic.

## 3. Ingestion Is Too Ephemeral

Ingest jobs live in memory:

- status disappears on restart
- failed errors are not stored
- queue is unbounded
- there is no simple recovery path

Minimal fix:

- add a small SQLite `ingest_jobs` table
- store job status and error
- add a queue max size
- add a simple retry count

Do not build a full distributed job system yet.

## 4. Remote Storage Is Not First-Class Enough

The code stores raw content only if it appears in `metadata["raw_text"]`. That makes raw storage feel accidental.

Minimal fix:

- make raw text/content a first-class ingest input
- store raw content before indexing
- save the storage key in the ingest job or document record

Do not build multipart upload, local spool, or object lifecycle policy yet. Leave that for later.

## 5. Config Exists But Adapters Can Ignore It

`WebsiteProjectAdapter.get_config()` returns hard-coded values such as `example.com`. This means SQLite config is not really the source of truth.

Minimal fix:

- keep `BaseProjectConfig`
- add optional `adapter_config`
- make website allowed domains come from config

Do not build many project types yet. Make one adapter honest first.

## 6. Concurrency Limits Protect the Wrong Work

The gateway limiter wraps plan preparation, not the expensive engine work. That means embedding, Qdrant search, reranking, and ingestion are not meaningfully limited per project/user.

Minimal fix:

- add a simple engine-level semaphore for search
- add a simple bounded ingest queue
- optionally add one embedding semaphore and one reranking semaphore

Do not add a complex fairness scheduler yet.

## 7. Generation Boundary Is Confusing

The docs say FaaS workers handle generation, but the server also has `Generate`. The engine generation path ignores adapter prompt builders and accepts chunks from the caller.

Minimal fix:

- choose one path for now
- recommended: keep this server focused on retrieval and ingestion
- mark `Generate` as experimental or remove it from the core path

Do not build a large generation orchestration layer yet.

## 8. Tests Are Too Mocked

Mocks are fine for unit tests, but the project needs a few real integration tests:

- Qdrant upsert/search/delete isolation
- SQLite config and ingest job persistence
- cache invalidation
- website adapter domain validation

Minimal fix:

- keep the current unit tests
- add a small integration test layer
- do not build a large load-test framework yet

## 9. The Structure Is Mostly Good, But The Package Boundary Is Too Eager

The directory structure is mostly minimal and extensible:

```text
core/
adapters/
gateway/
engine/
services/
storage/
config/
grpc/
health/
versioning/
```

This is a reasonable shape. It does not need a major rewrite.

The main structural problem is import behavior. The top-level package imports many modules immediately, including Qdrant-dependent modules. That makes the whole package depend on all optional/runtime dependencies even when a test or caller only needs cache, models, config, or health.

Minimal fix:

- keep the folder structure
- avoid large top-level imports from `rag_server/__init__.py`
- import concrete services from their own modules
- treat `generation`, `health`, and `versioning` as optional leaf capabilities rather than central core

Do not split the repo into many packages yet. Just make imports lighter and boundaries clearer.

## The Ugly

## Data Safety Is the Only Truly Urgent Ugly Part

The project does not need every advanced platform feature right now. But it must not accidentally overwrite or delete another user's chunks.

The urgent problems are:

- point ID collisions
- delete too broad
- ingest status lost
- raw storage not guaranteed

Fix those first.

## Recommended Minimal Core Model

Keep the current model, but tighten it:

```text
project_id
user_id
kb_id
doc_id
data_type
chunk_id
chunk_index
text
metadata
visibility: private | shared
embedding_version
chunker_version
content_hash
```

Notes:

- `visibility` replaces over-complicated service-scope models for now.
- `data_type` lets the same RAG store docs, memories, preferences, running records, and other text-first records.
- `content_hash` helps deduplicate and rebuild.
- `embedding_version` and `chunker_version` help cache/version correctness.
- More fields can be added later if product needs demand it.

## Recommended Minimal Ingest Flow

```text
request
  -> validate project_id/user_id/kb_id/doc_id
  -> store raw content in object storage
  -> create durable ingest job
  -> parse/chunk through adapter
  -> embed chunks
  -> upsert into Qdrant with safe point IDs
  -> mark job completed
  -> invalidate caches
```

If object storage is unavailable, the system should fail clearly or run in explicit local-dev mode.

## Recommended Minimal Search Flow

```text
request
  -> validate project_id/user_id/query
  -> build server-side filter
  -> check retrieval cache
  -> embed query
  -> Qdrant search with project/user/shared filters
  -> optional rerank
  -> return chunks
```

Keep generation outside this flow until retrieval is solid.

## Keep For Later

These are useful, but should remain future development:

- organization-level tenancy
- service namespaces
- mTLS
- distributed job queue
- complex RBAC
- multi-region recovery
- full observability stack
- hybrid search
- advanced memory decay/ranking
- preference-specific structured storage
- complex cache stampede prevention
- automatic Qdrant snapshot orchestration

Do not design them out. Just do not implement them yet.

## Final Verdict

This repo should become a small dependable RAG core, not a big platform.

The right next milestone is:

```text
Safe project/user-scoped ingest, search, delete, and raw document backup.
```

Once that is reliable, future capabilities can be added naturally.

## 2026-06-05 Source Review Addendum

I re-read the related implementation files before updating the documentation:

```text
rag_server/core/models.py
rag_server/adapters/base.py
rag_server/adapters/website.py
rag_server/config/repository.py
rag_server/gateway/handler.py
rag_server/engine/engine.py
rag_server/services/vector_store.py
rag_server/services/cache.py
rag_server/services/embedding.py
rag_server/services/reranker.py
rag_server/services/generation.py
rag_server/storage/base.py
rag_server/storage/memory.py
rag_server/storage/filesystem.py
rag_server/storage/s3.py
rag_server/versioning/manager.py
rag_server/health/health.py
rag_server/grpc/server.py
proto/rag_service.proto
tests/test_phase*_*.py
```

### Confirmed By Code

- The adapter boundary is real and worth preserving.
- The gateway rejects raw client filters for search and builds server-side scope.
- Qdrant filters include `project_id`, allowed `user_id` values, optional `kb_id`, and optional `doc_id`.
- Query-time text comes from Qdrant payloads, not object storage.
- Embedding and reranking use executor-backed async wrappers.
- Tier-1 retrieval cache and Tier-2 SQLite response cache exist.
- Object storage has memory, filesystem, and S3-compatible implementations.
- gRPC delegates to gateway and engine rather than embedding logic directly in transport code.

### Still Confirmed As Gaps

- `BaseDocument`, `BaseChunk`, and `BaseChunkPayload` do not yet have `data_type`, `visibility`, `content_hash`, `embedding_version`, or `chunker_version` fields.
- `QdrantStore.upsert()` still uses `payload.chunk_id` as point ID.
- `QdrantStore.delete_document()` still filters only by `doc_id`.
- `RagEngine._ingest_status` is in memory, and `_ingest_queue` is unbounded.
- Ingest failures set status to `FAILED` but do not preserve the exception text in a durable job record.
- Raw storage still depends on `document.metadata["raw_text"]`.
- `make_storage_key()` is only `project_id/user_id/doc_id`; it does not include `kb_id` or `content_hash`.
- `WebsiteProjectAdapter.get_config()` still returns hard-coded config.
- `IngestRequest` in `proto/rag_service.proto` has no first-class raw content field.
- `Generate` exists as a server endpoint, but it bypasses adapter prompt builders and should remain experimental.
- `rag_server/__init__.py` eagerly imports heavy optional modules.

### Documentation Corrections Made

- `progress.md` now describes the project as a prototype/core scaffold rather than `~97%` production-complete.
- `README.md` now explains the actual architecture, known gaps, and development commands.
- `report.md` now records this source-backed addendum.

No code changes were made during this documentation update.
