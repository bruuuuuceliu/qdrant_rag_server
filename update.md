# Minimal RAG Server Update Plan

Updated on: 2026-06-04  
Goal: make the current RAG server essential, reliable, and easy to extend without turning it into an overbuilt platform.

## Direction

The project should stay small.

Build a dependable core:

- project-scoped RAG
- user-private and project-shared data
- document ingestion
- text-first records for different data types
- Qdrant retrieval
- raw document backup in remote storage
- simple durable ingest status
- small adapter system
- focused tests

Leave larger platform features for later.

## Development Environment

Run project commands inside the `evo` conda environment:

```bash
source /home/bruce/miniconda3/etc/profile.d/conda.sh
conda activate evo
```

Current note:

- `evo` uses Python 3.12.13.
- `pytest` is available in `evo`.
- Test collection currently fails because `qdrant_client` is not installed.
- The failure also reveals an import-structure issue: `rag_server/__init__.py` eagerly imports Qdrant-dependent modules.

Minimal environment update:

```bash
python -m pip install -e ".[dev]"
```

Only do this when dependency installation is intended. The code plan itself should not depend on installing extra packages unless the phase requires test execution.

## Non-Goals For Now

Do not implement these yet:

- organization-level tenancy
- service namespaces
- complex RBAC
- mTLS
- distributed job queues
- multi-region recovery
- full observability stack
- hybrid search
- advanced memory ranking
- preference-specific databases
- automatic snapshot orchestration
- large plugin architecture

The code should leave room for these, but not carry their weight now.

## Extensibility Rule: Text First

The same RAG server may store many kinds of data:

- documentation
- agent memories
- user preferences
- running records
- activity history
- logs
- lightweight notes

For now, that is supported through a text-first model:

```text
source record -> adapter -> text chunks + metadata -> Qdrant
```

The RAG server should not become the structured source of truth. It only stores the searchable text representation and metadata.

Minimal requirement:

- add `data_type`
- keep `metadata` flexible
- keep adapters responsible for converting source data into text
- keep the engine generic
- do not branch in the engine for each data type

Example:

```text
data_type = "running_record"
text = "User ran 5.2 km on 2026-06-04 in 28 minutes."
metadata = {"distance_km": 5.2, "duration_seconds": 1680}
```

## Phase 0: Documentation and Project Shape

### Design Updates

- Rewrite `progress.md` to say this is a prototype/core scaffold, not 97% production complete.
- Expand `README.md` just enough to explain:
  - what the server does
  - what is implemented
  - what is intentionally future work
  - how to run tests
  - how to start a local server
- Keep `report.md` and `update.md` aligned with a minimal core direction.

### Code Updates

- Add a small bootstrap module, for example `rag_server/app.py`.
- It should wire existing pieces:
  - config repository
  - website adapter
  - adapter registry
  - gateway
  - Qdrant store
  - caches
  - engine
  - gRPC server
- Add `.env.example` for local settings.
- Keep commands and docs based on `conda activate evo`.
- Review the current module structure before changing code.
- Keep the current folders if possible:

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

- Do not perform a broad restructure just for neatness.
- Do fix structure issues that hurt minimal extensibility:
  - reduce eager imports in `rag_server/__init__.py`
  - keep optional/heavy dependencies in leaf modules
  - avoid making cache/config/model tests import Qdrant by accident
  - keep `generation`, `health`, and `versioning` as leaf capabilities unless they are needed by the core path

### Acceptance Criteria

- The project status is honest.
- A developer can understand the current shape in under 10 minutes.
- There is one obvious place to start the server.
- Basic imports for models/config/cache do not require Qdrant dependencies.

## Phase 1: Fix Data Safety First

### Design Updates

Keep the current tenant model:

```text
project_id
user_id
kb_id
doc_id
```

Add only the minimum extra fields:

```text
data_type
visibility: private | shared
content_hash
embedding_version
chunker_version
```

Do not add organization/service/namespace models yet.

### Code Updates

- Add safe Qdrant point IDs.
- Point IDs should include:

```text
project_id
user_id
kb_id
doc_id
data_type
chunk_index
chunker_version
```

- Stop using `chunk_id` alone as Qdrant point ID.
- Update delete to filter by:

```text
project_id
user_id
kb_id
doc_id
```

- Do not accept raw `collection_name` from higher-level delete calls.
- Validate vector count matches payload count before upsert.
- Validate vector dimension before upsert.
- Add `data_type` to base document/chunk/payload models with a conservative default such as `document`.
- Ensure adapters can set `data_type` without engine changes.

### Acceptance Criteria

- Two users can upload the same `doc_id` without collision.
- Deleting one user's document cannot delete another user's document.
- Bad embedding output fails loudly instead of silently dropping chunks.
- A new text-first data type can be added through an adapter without editing the engine.

## Phase 2: Make Ingest Minimally Durable

### Design Updates

Use a small SQLite-backed job table. Do not add a distributed queue.

Minimal ingest states:

```text
pending
running
completed
failed
```

Optional but useful:

```text
retry_count
error
created_at
updated_at
raw_storage_key
```

### Code Updates

- Add `SQLiteIngestJobRepository`.
- Persist job status when scheduled.
- Update job status when running/completed/failed.
- Store failure error text.
- Add a max size to the in-memory ingest queue.
- Return a clear saturation error when the queue is full.
- On startup, mark previously running jobs as failed or pending based on a simple policy.

### Acceptance Criteria

- Job status survives process restart.
- Failed jobs include an error message.
- The ingest queue cannot grow forever.

## Phase 3: Make Raw Storage Explicit

### Design Updates

Raw document content should be a first-class ingest input, not hidden in `metadata["raw_text"]`.

Keep object storage simple:

```text
project_id/user_id/kb_id/doc_id/content_hash
```

Remote storage remains backup/rebuild storage only. Query-time retrieval still uses Qdrant payload text.

### Code Updates

- Add `raw_text` or `raw_content` to `IngestRequest`.
- Store raw content in object storage before Qdrant upsert.
- Save `raw_storage_key` in the ingest job.
- Keep local memory/filesystem storage for tests and development.
- Add `head()` or improve `exists()` later, but do not block this phase on a full S3 rewrite.

### Acceptance Criteria

- Every successful ingest with raw content has a storage key.
- Query search does not read from object storage.
- Re-indexing later has a clear raw source to read from.

## Phase 4: Make Config Real But Small

### Design Updates

Project config should be the source of truth.

Add only one flexible field:

```text
adapter_config
```

For website projects, store:

```text
domains
default_locale
```

Do not add many project types yet.

### Code Updates

- Add `adapter_config_json` to the SQLite config table.
- Update `BaseProjectConfig` or config record to carry adapter config.
- Make `WebsiteProjectAdapter` use config values instead of hard-coded `example.com`.
- Enforce allowed domains during website ingest.
- Preserve URL/title metadata in chunks.

### Acceptance Criteria

- Website allowed domains come from project config.
- Disallowed website URLs are rejected.
- Website payloads include useful URL metadata.

## Phase 5: Simple Resource Limits

### Design Updates

Do not build a complex scheduler.

Use a few simple limits:

- max concurrent searches
- max concurrent ingests
- max ingest queue size
- optional embedding semaphore
- optional reranking semaphore

### Code Updates

- Move search concurrency limiting around the full `engine.search()` operation.
- Keep gateway validation, but do not treat it as resource protection.
- Add engine-level semaphores.
- Add clear errors for saturation.

### Acceptance Criteria

- A burst of requests does not create unbounded work.
- Saturation returns a clear error.
- Tests cover queue-full behavior.

## Phase 6: Clarify Generation

### Design Updates

For now, keep this server focused on retrieval and ingestion.

Generation should be treated as optional/experimental unless the product clearly needs server-side generation.

Recommended minimal choice:

- RAG server returns chunks.
- Caller/FaaS builds prompts and calls LLM.
- Keep adapter `build_prompt()` as a helper, not the main server path.

### Code Updates

- Mark gRPC `Generate` and `RagEngine.generate()` as experimental in docs.
- Do not expand generation features yet.
- If keeping generation tests, ensure cache keys include model name at minimum.

### Acceptance Criteria

- Core RAG path does not depend on OpenRouter.
- Retrieval works independently from generation.

## Phase 7: Focused Tests

### Design Updates

Tests should prove the minimal safety guarantees.

### Code Updates

Add or update tests for:

- safe point IDs
- delete isolation
- vector/payload count mismatch
- ingest job persistence
- queue saturation
- raw storage key creation
- website domain validation
- cache invalidation after ingest

Keep integration tests modest:

- use fake/in-memory services where appropriate
- add real Qdrant/MinIO tests later as optional integration tests

### Acceptance Criteria

- Unit tests catch tenant collision bugs.
- Unit tests catch unsafe deletes.
- The core ingest/search/delete behavior is covered.

## Phase 8: Leave Future Hooks

### Design Updates

Add comments or simple extension points for future features, but do not implement them now.

Future hooks:

- organization ID
- service namespace
- richer authorization
- distributed jobs
- advanced retrieval filters
- real S3 client replacement
- Qdrant snapshots
- Prometheus/OpenTelemetry

### Code Updates

- Keep models easy to extend.
- Avoid hard-coded assumptions that block future fields.
- Keep adapter boundary clean.
- Keep storage abstraction clean.

### Acceptance Criteria

- The minimal system is not overbuilt.
- Future growth is possible without rewriting the whole engine.

## Recommended Implementation Order

1. Documentation honesty and bootstrap.
2. Minimal structure cleanup, especially top-level eager imports.
3. Safe Qdrant point IDs.
4. Scoped delete.
5. Vector/payload validation.
6. Durable ingest job table.
7. Bounded ingest queue.
8. Explicit raw content and storage key.
9. Config-backed website domains.
10. Simple engine-level resource limits.
11. Focused tests.

## Immediate Code Checklist

### Must Do

- Run commands in `conda activate evo`.
- Fix top-level imports so unrelated tests do not require Qdrant.
- Stop using `chunk_id` alone as Qdrant point ID.
- Make delete tenant-safe.
- Add vector/payload validation.
- Persist ingest job status.
- Store ingest error messages.
- Add queue max size.
- Make raw content explicit.
- Make website domains config-backed.

### Should Do

- Set real `elapsed_ms` in search results.
- Add `data_type`.
- Add `content_hash`.
- Add `visibility`.
- Add `adapter_config`.
- Mark generation as experimental.

### Later

- Real S3 client hardening.
- Real Qdrant integration tests.
- Advanced auth.
- Distributed job queue.
- Full metrics stack.
- Snapshot/rebuild automation.

## Final Target

The next stable milestone should be:

```text
Minimal safe RAG core:
project/user-scoped ingest, search, delete, cache invalidation, and raw backup.
```

That is enough foundation. Build the rest only when product needs force it.
