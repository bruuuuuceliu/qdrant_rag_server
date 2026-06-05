# Information Retrieval Engine Detailed Development Plan

Date: 2026-06-05
Target project: `/home/bruce/workplace/qdrant_rag_server`
Scope: planning and documentation for the standalone qdrant information-retrieval server only. Do not apply this plan to EvoAgentX.

## 0. Project Purpose And Design Guardrails

This project should be treated as a minimal information-retrieval service, not only as an answer-generation RAG server.

Core purpose:

- Provide the smallest useful retrieval core: ingest data, index it, search it, delete it, track job status, and preserve raw source content when configured.
- Keep RAG-style generation optional. Retrieval must remain useful without an LLM, OpenRouter, prompt building, or answer synthesis.
- Support vector search now, while leaving first-class space for BM25, hybrid retrieval, metadata-only lookup, graph/relationship lookup, and future retrievers.
- Allow different data types to carry different schemas, parsing logic, indexing logic, retrieval methods, and filter semantics.
- Keep components replaceable. Request reading, status updates, storage, config, retrievers, rerankers, embeddings, and generation clients should depend on small protocols rather than concrete classes.
- Keep the implementation essential. Avoid broad tenancy management, RBAC platforms, workflow engines, distributed schedulers, or full observability systems until the minimal retrieval core is safe.

Design guardrails:

1. The engine orchestrates; it should not own parsing, storage implementation details, retriever internals, or transport-specific request shapes.
2. The gateway validates and normalizes request intent; it should not know Qdrant-specific filter syntax.
3. Adapters convert typed data into common retrieval records; they should be replaceable per project type or data type.
4. Retrievers own retrieval method details. Vector, BM25, hybrid, and future retrievers should share one result contract.
5. Job status should be updated through a status repository/protocol, not by hard-coded in-memory dicts.
6. User-provided keys and per-request provider settings should be accepted where needed. The service must not rely on default API keys for generation.
7. Optional components must have clear disabled behavior. A retrieval-only deployment should not crash because reranking, object storage, or generation is not configured.

Replaceable component targets:

```text
transport/request reader     gRPC today; future HTTP, queue, CLI, or internal SDK
gateway                      validation, defaults, scope, and request normalization
data adapter                 project/data-type parsing, chunking, payload shape, prompts
retriever                    vector, BM25, hybrid, metadata lookup, future methods
reranker                     optional candidate reranking after retrieval merge
embedding provider           any provider with encode/encode_batch
job status repository        memory for tests/dev, SQLite for local durable state, future external store
object storage               memory, filesystem, S3-compatible, future stores
generation client            optional OpenRouter or other LLM provider, request-scoped keys
config repository            source of project, adapter, retrieval, and pipeline configuration
```

Configuration expectations:

- Project config should define enabled retrievers, retriever weights, candidate counts, reranker choice, data-type settings, adapter settings, and cache policy.
- Request config may override safe per-call settings such as selected data types, selected KBs, model name, generation parameters, and user-supplied provider keys.
- Defaults should be conservative and local: one default KB, vector-only retrieval, no generation unless explicitly configured, and no hidden provider credentials.

## 1. Current Reading Summary

The base has moved forward. Several earlier plan items are now implemented and should no longer be treated as future work.

Implemented or mostly implemented:

- Text-first base payload fields exist in `rag_server/core/models.py`:
  - `data_type`
  - `visibility`
  - `content_hash`
  - `embedding_version`
  - `chunker_version`
- `Visibility` exists with `private` and `shared` values.
- Base payloads write those fields to Qdrant payloads.
- `WebsiteProjectAdapter` propagates the new fields from document to chunk to payload.
- Qdrant point IDs are deterministic and scoped through `make_qdrant_point_id()`.
- Qdrant upsert validates vector count and vector dimension.
- Qdrant delete is scoped by `project_id`, `user_id`, `kb_id`, and `doc_id`.
- Qdrant imports have a fallback model layer, so tests for models and filters do not require `qdrant_client` at import time.
- A minimal `rag_server/app.py` bootstrap exists.
- `.env.example` exists.
- Embedding and reranker services offload CPU-bound model work with `run_in_executor()`.
- OpenRouter generation client uses async `httpx`.
- Health and metrics classes exist.
- `create_app()` now passes the initialized `EmbeddingService` object into `RagEngine`, so search and ingest share a provider with `encode()` and `encode_batch()`.
- `create_app()` wires metrics, health checking, and opt-in OpenRouter generation.
- Generation-disabled deployments return an explicit unavailable error instead of failing through a missing client.
- Search responses now populate `elapsed_ms` for normal results and cache hits.
- In-memory ingest status now records `doc_id`, error text, and timestamps.
- Object storage abstractions exist for memory, filesystem, and S3-compatible storage.
- Missing or blank ingest `kb_id` is normalized to a shared default KB id, so callers do not need to create KB separation unless they want it.
- Tests now cover part of the new base field behavior, Qdrant point safety, vector validation, scoped delete, storage, generation, health, and end-to-end scaffolding.

Still not implemented or unsafe:

- SQLite repositories and cache methods are declared `async` but run synchronous `sqlite3` work directly in the event loop.
- Filesystem object storage methods are declared `async` but use blocking file I/O directly.
- Ingest jobs are memory-only and are lost on restart.
- Ingest queue is unbounded.
- Ingest status still has no durable persisted record or storage key.
- gRPC and gateway request models still do not expose the new base fields as typed fields.
- Search filters still do not filter by `data_type`, `visibility`, `embedding_version`, or `chunker_version`.
- Raw content still travels through `metadata["raw_text"]` instead of a typed request field.
- Raw storage keys are still `{project_id}/{user_id}/{doc_id}`, which can collide across KBs and data types.
- `WebsiteProjectAdapter.get_config()` still hard-codes project config.
- `WebsiteProjectAdapter.parse_document()` does not enforce allowed domains from config.
- `create_app()` does not wire reranker, version manager, or object storage.
- Generation cache key does not include model or generation parameters.
- `VersionManager` directly uses private methods on `SQLiteProjectConfigRepository` and also performs blocking SQLite operations.
- S3 storage uses a fragile Host header and canonical path implementation.

## 2. Async Design Standard

Async is a core requirement for this project. The design standard is:

1. Public service methods may be `async` only if their heavy work is actually non-blocking or offloaded.
2. Network I/O must use async clients, such as async gRPC, async Qdrant, and async `httpx`.
3. CPU-bound model work must use an executor or dedicated worker pool.
4. SQLite and filesystem I/O must not run directly on the event loop under production request paths.
5. Background ingest must use bounded queues, durable state, cancellation handling, and explicit startup/shutdown lifecycle.
6. Batch operations should schedule bounded async work; they should not create unlimited tasks or unbounded memory pressure.
7. Reranking and independent retrieval methods should run concurrently where possible, then merge and rerank.
8. Test coverage must include async behavior, not only happy-path mocks.

Current async audit:

| Area | Current state | Async verdict | Action |
| --- | --- | --- | --- |
| gRPC server | Uses `grpc.aio` | Good | Keep. |
| Qdrant | Uses `AsyncQdrantClient` | Good | Keep. |
| Embedding | Offloads model load and encode to executor | Good internally | Keep provider protocol. |
| Reranker | Offloads model load and rerank to executor | Good internally | Wire in app optionally. |
| OpenRouter | Uses async `httpx`; app wiring is opt-in | Good | Keep request-scoped keys. |
| S3 storage | Uses async `httpx` | Mostly good | Fix signing/host/canonical path. |
| Filesystem storage | Async method names, blocking file I/O | Not async-safe | Offload to thread or mark dev-only. |
| Config repository | Async method names, blocking sqlite | Not async-safe | Move to `aiosqlite` or executor-backed repository. |
| Tier2 cache | Async method names, blocking sqlite | Not async-safe | Move to shared async DB strategy. |
| Version manager | Blocking sqlite and private repo access | Not async-safe | Refactor after repository base is fixed. |
| Ingest workers | Async queue/workers | Partially good | Add bounded queue, durable jobs, better lifecycle. |
| Metrics | In-memory counters, no lock | OK in single loop | Add lock if used across threads. |

## 3. Desired Architecture

The engine should remain small and project-scoped. It should not become a tenant management service or broad RBAC platform.

Primary layers:

```text
transport/          gRPC and future API adapters
gateway/            request validation, scope enforcement, concurrency limits
adapters/           project/data-type parsing, chunking, payloads, prompts
engine/             async orchestration for ingest, retrieve, delete, raw access
retrieval/          vector/BM25/hybrid/metadata retrievers and rerank coordinator
services/           embedding, reranker, generation, vector store, cache
storage/            object storage for raw content
config/             async project config repository
jobs/               async durable ingest job repository
versioning/         version metadata and future conflict policy
health/             health and metrics
```

Required extension contracts:

```python
class RequestReader(Protocol):
    async def read_search(self, raw: object) -> SearchRequest: ...
    async def read_ingest(self, raw: object) -> IngestRequest: ...

class JobStatusRepository(Protocol):
    async def create(self, job: IngestJobRecord) -> None: ...
    async def update(self, job_id: str, status: str, **fields: object) -> None: ...
    async def get(self, job_id: str) -> IngestJobRecord | None: ...

class DataTypeAdapter(Protocol):
    data_type: str
    async def parse(self, request: IngestRequest) -> BaseDocument: ...
    async def chunk(self, document: BaseDocument) -> list[BaseChunk]: ...
    async def payload(self, chunk: BaseChunk) -> BaseChunkPayload: ...
    async def build_filter(self, request: SearchRequest) -> BaseRetrievalFilter: ...

class Retriever(Protocol):
    name: str
    async def retrieve(self, query: RetrievalQuery) -> list[RetrievedChunk]: ...
```

These protocols should stay small. Concrete classes can be richer, but the engine should depend on the narrow contracts.

Project data hierarchy:

```text
Level 1: data purpose
  data_type = project_document | agent_memory | running_record | case_note | ...

Level 2: project separation
  project_id

Level 3: project/user visibility
  user_id = real user id for private records
  user_id = __shared__ for shared project records
  visibility = private | shared as a payload marker
```

The current code partially satisfies this:

- Level 1 exists in payloads through `data_type`, but search/gRPC do not expose it yet.
- Level 2 exists through `project_id`, collection naming, and Qdrant filters.
- Level 3 exists through `allowed_user_ids`, but `visibility` is not enforced consistently at API level.
- KB separation is optional by default. Missing or blank `kb_id` should use the default KB, while explicit `kb_ids` still allow targeted retrieval.

## 4. Updated Development Order

### Phase 1: Fix Runtime-Breaking App And Engine Wiring

Goal: make the current runnable app actually support both search and ingest.

Files:

```text
rag_server/services/embedding.py
rag_server/engine/engine.py
rag_server/app.py
rag_server/services/reranker.py
rag_server/services/generation.py
rag_server/health/health.py
rag_server/grpc/server.py
tests/test_phase3_engine.py
tests/test_phase5_ingestion.py
tests/test_phase11_e2e.py
```

Actions:

- Replace the ambiguous `embed_fn` dependency with an `EmbeddingProvider` protocol.
- Engine search should call `embedding_provider.encode(query)`.
- Engine ingest should call `embedding_provider.encode_batch(texts)`.
- `EmbeddingService.initialize()` can return `self`, or `app.py` can pass `embedding_service` after initializing it.
- Keep a compatibility path only if it does not preserve the broken callable/object mismatch.
- Wire `OpenRouterClient` only if generation is enabled; otherwise `Generate` should return a clear unavailable error.
- Wire `MetricsCollector` into `RagEngine` and `HealthChecker`.
- Wire `HealthChecker` into `serve_grpc()`.
- Add app settings for optional reranker, object storage, OpenRouter, and health components.
- Ensure app shutdown closes every initialized async/executor resource.

Suggested protocol:

```python
class EmbeddingProvider(Protocol):
    async def encode(self, text: str) -> list[float]: ...
    async def encode_batch(self, texts: list[str]) -> list[list[float]]: ...
```

Acceptance:

- A `create_app()` instance can run search and ingest without interface errors.
- `Generate` either works because OpenRouter is wired or fails with an intentional service-unavailable response.
- App health reflects the actual wired components.
- Tests cover app wiring with a fake embedding provider that has both methods.

### Phase 2: Make Local Persistence Truly Async-Safe

Goal: remove fake-async blocking SQLite and filesystem operations from request paths.

Files:

```text
pyproject.toml
rag_server/config/repository.py
rag_server/services/cache.py
rag_server/versioning/manager.py
rag_server/storage/filesystem.py
tests/test_phase1_core.py
tests/test_phase7_cache.py
tests/test_phase9_versioning.py
tests/test_phase5_ingestion.py
```

Preferred design:

- Add `aiosqlite` as a dependency, or create a small executor-backed database runner if adding a dependency is not desired.
- Use one consistent async DB pattern for config, cache, job repository, and version metadata.
- Enable SQLite WAL mode and `busy_timeout` during initialization.
- Keep each operation short and connection-scoped unless a transaction requires grouping.
- Do not let `VersionManager` call private repository methods.
- For filesystem storage, use `asyncio.to_thread()` around `Path.write_bytes`, `Path.read_bytes`, `Path.unlink`, and existence checks, or clearly restrict filesystem storage to tests/dev.

Repository shape:

```python
class AsyncProjectConfigRepository(Protocol):
    async def initialize(self) -> None: ...
    async def upsert_project(self, config: BaseProjectConfig) -> None: ...
    async def get_project_config(self, project_id: str) -> BaseProjectConfig: ...
    async def get_project_type(self, project_id: str) -> str: ...
    async def set_active_embedding_version(self, project_id: str, version: str) -> None: ...
```

Acceptance:

- No production async method performs direct blocking sqlite calls.
- Cache and config DB operations do not stall unrelated concurrent gRPC requests.
- Version manager uses a public async repository/database interface.
- Filesystem storage is either offloaded or documented as dev-only and not wired in production app by default.

### Phase 3: Fix Search And Job Result Correctness

Goal: return truthful runtime status from existing APIs before adding bigger APIs.

Files:

```text
rag_server/engine/engine.py
rag_server/grpc/server.py
rag_server/core/models.py
tests/test_phase3_engine.py
tests/test_phase5_ingestion.py
```

Actions:

- Set `SearchResult.elapsed_ms` on normal search results and cache hits.
- Store elapsed time in tier-1 search cache after it is computed.
- Extend `IngestResult` with:
  - `doc_id`
  - `error`
  - optional `created_at`
  - optional `updated_at`
- On ingest failure, record the exception message in `IngestResult.error`.
- Call `queue.task_done()` in the ingest loop after each job.
- Update metrics queue depth when scheduling and completing jobs.
- Decide how cancellation should update running jobs during shutdown.

Acceptance:

- Search response elapsed time is nonzero for nontrivial calls.
- `GetIngestJobStatus` returns useful `doc_id` and `error` values.
- Failed ingest jobs are diagnosable without reading logs.

### Phase 4: Durable Bounded Ingest Jobs

Goal: make async ingest recoverable and safe under load.

Files:

```text
rag_server/jobs/__init__.py
rag_server/jobs/base.py
rag_server/jobs/sqlite.py
rag_server/engine/engine.py
rag_server/app.py
rag_server/grpc/server.py
.env.example
tests/test_ingest_jobs.py
tests/test_phase5_ingestion.py
tests/test_phase11_e2e.py
```

Actions:

- Add `IngestJobRepository` with async methods.
- Add SQLite implementation using the async DB strategy from Phase 2.
- Add bounded ingest queue size config, for example `RAG_INGEST_QUEUE_SIZE`.
- Use `put_nowait()` or timeout-based queue submission so overload is explicit.
- Persist job status transitions:
  - `pending`
  - `running`
  - `completed`
  - `failed`
- Persist `error`, `doc_id`, `kb_id`, `data_type`, `visibility`, `raw_storage_key`, and `content_hash`.
- On startup, handle old `running` jobs with a clear policy:
  - mark as failed with `interrupted by restart`, or
  - requeue if enough request data is persisted.

Minimal schema:

```sql
CREATE TABLE ingest_jobs (
  job_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  kb_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  data_type TEXT NOT NULL,
  visibility TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  content_type TEXT NOT NULL,
  status TEXT NOT NULL,
  raw_storage_key TEXT,
  content_hash TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Acceptance:

- Job status survives process restart.
- Queue overload returns a clear gRPC error instead of unbounded memory growth.
- Durable job updates are awaited and do not block the event loop.

### Phase 5: Expose Text-First Fields At Gateway And gRPC

Goal: stop hiding core routing/filter fields inside metadata.

Files:

```text
proto/rag_service.proto
rag_server/grpc/rag_service_pb2.py
rag_server/grpc/rag_service_pb2_grpc.py
rag_server/gateway/handler.py
rag_server/grpc/server.py
rag_server/core/models.py
tests/test_phase2_gateway.py
tests/test_phase11_e2e.py
```

Actions:

- Add typed fields to `IngestRequest`:
  - `data_type`
  - `visibility`
  - `content_hash`
  - `chunker_version`
  - `raw_text` or `raw_content`
- Add typed fields to `SearchRequest`:
  - `repeated string data_types`
  - `repeated string doc_ids`
  - optional version filters later.
- Add fields to `ChunkResult`:
  - `data_type`
  - `visibility`
  - `content_hash`
  - `embedding_version`
  - `chunker_version`
- Preserve `metadata` in search responses and generate requests.
- Validate visibility at the gateway.
- Continue rejecting raw client-supplied Qdrant filters.

Acceptance:

- Clients can ingest project documents, memories, and running records without metadata conventions.
- Clients can search only selected data types.
- Search results expose enough identity/version fields for debugging and downstream reranking.

### Phase 6: Extend Retrieval Filters For Purpose And Version

Goal: make read isolation match the payload model.

Files:

```text
rag_server/core/models.py
rag_server/adapters/base.py
rag_server/adapters/website.py
rag_server/engine/engine.py
tests/test_phase1_core.py
tests/test_phase3_engine.py
```

Actions:

- Add to `BaseRetrievalFilter`:
  - `data_types: tuple[str, ...] = ()`
  - `visibilities: tuple[str, ...] = ()`
  - `embedding_versions: tuple[str, ...] = ()`
  - `chunker_versions: tuple[str, ...] = ()`
- Pass request-level `doc_ids` and `data_types` through adapter filter construction.
- Update `_build_qdrant_filter()` to add match-value or match-any conditions.
- Keep `allowed_user_ids` as the hard access pattern. Do not replace it with `visibility` alone.

Acceptance:

- Query for `project_document` does not search `agent_memory` unless requested.
- Shared project data still works through `user_id IN (user_id, __shared__)`.
- Optional version filters are supported without changing payload structure again.

### Phase 7: Typed Raw Content And Atomic Storage Flow

Goal: make raw storage explicit and collision-safe.

Files:

```text
rag_server/storage/base.py
rag_server/storage/memory.py
rag_server/storage/filesystem.py
rag_server/storage/s3.py
rag_server/engine/engine.py
rag_server/gateway/handler.py
proto/rag_service.proto
tests/test_phase5_ingestion.py
```

Actions:

- Replace `metadata["raw_text"]` ingestion with a typed raw content field.
- Compute `content_hash` when the client does not provide one.
- Expand storage key identity from:

```text
{project_id}/{user_id}/{doc_id}
```

  to:

```text
{project_id}/{user_id}/{kb_id}/{data_type}/{doc_id}/{content_hash}
```

- Store raw content before vector upsert.
- Persist `raw_storage_key` on the ingest job.
- If raw storage succeeds but vector upsert fails, keep the raw object and mark the job failed.
- Make delete use the durable job/raw metadata where possible instead of guessing storage keys.

Acceptance:

- Same `doc_id` in different KBs or data types cannot overwrite raw content.
- Failed vector indexing does not lose raw source data.
- Raw storage can be used later for re-indexing.

### Phase 8: Service-Level Batch Ingest

Goal: support batches at the API/job level, not by forcing every low-level vector operation into one huge batch.

Files:

```text
proto/rag_service.proto
rag_server/gateway/handler.py
rag_server/engine/engine.py
rag_server/grpc/server.py
rag_server/jobs/base.py
rag_server/jobs/sqlite.py
tests/test_batch_ingest.py
```

Batch meaning in this project:

- Read document inputs from a list.
- Filter selected docs by `doc_id`, `kb_id`, `data_type`, document name, or metadata.
- Schedule selected docs as child ingest jobs.
- Return one `batch_id` and child `job_id`s.
- Keep bounded concurrency and durable status.

Suggested proto:

```protobuf
message BatchIngestRequest {
  repeated IngestRequest documents = 1;
  repeated string include_doc_ids = 2;
  repeated string include_kb_ids = 3;
  repeated string include_data_types = 4;
}

message BatchIngestResponse {
  string batch_id = 1;
  repeated IngestResponse jobs = 2;
}
```

Acceptance:

- Batch submission cannot bypass queue bounds.
- Batch status summarizes completed, failed, pending, and running child jobs.
- Single-document ingest remains a simple path.

### Phase 9: Config-Backed Adapters

Goal: make project-specific adapters use project config instead of hard-coded values.

Files:

```text
rag_server/core/models.py
rag_server/config/repository.py
rag_server/adapters/base.py
rag_server/adapters/website.py
rag_server/app.py
tests/test_phase1_core.py
tests/test_phase6_website_adapter.py
```

Actions:

- Add `adapter_config: dict[str, Any]` to `BaseProjectConfig` and repository storage.
- Store website settings such as domains, crawl rules, sitemaps, and locale in `adapter_config`.
- Inject a config provider/repository into `WebsiteProjectAdapter`.
- Convert base config plus adapter config into `WebsiteProjectConfig`.
- Enforce domain validation before ingest.

Acceptance:

- Website adapter no longer hard-codes `example.com`.
- Project-specific website domains are loaded from config.
- Invalid website source URLs are rejected before indexing.

### Phase 10: Retrieval Framework For Vector, BM25, Hybrid, Rerank

Goal: make retrieval extensible beyond vector RAG while preserving current vector behavior.

New files likely needed:

```text
rag_server/retrieval/__init__.py
rag_server/retrieval/base.py
rag_server/retrieval/vector.py
rag_server/retrieval/bm25.py
rag_server/retrieval/coordinator.py
rag_server/retrieval/rerank.py
```

Suggested interfaces:

```python
@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    project_id: str
    user_id: str
    query: str
    kb_ids: tuple[str, ...] = ()
    doc_ids: tuple[str, ...] = ()
    data_types: tuple[str, ...] = ()
    include_shared: bool = True
    top_k: int = 5
    candidate_count: int = 20

@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    payload: dict[str, Any]
    score: float
    source: str

class Retriever(Protocol):
    name: str
    async def retrieve(
        self,
        query: RetrievalQuery,
        config: BaseProjectConfig,
        retrieval_filter: BaseRetrievalFilter,
    ) -> list[RetrievedChunk]: ...
```

Coordinator behavior:

```python
async def retrieve(query, config, retrieval_filter):
    tasks = [
        retriever.retrieve(query, config, retrieval_filter)
        for retriever in enabled_retrievers(config)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    candidates = merge_and_dedupe(results)
    if reranker is not None:
        return await reranker.rerank(query.query, candidates)
    return candidates[:query.top_k]
```

Async requirements:

- Vector embedding can run in parallel with lexical/BM25 retrieval.
- Independent retrievers should run concurrently.
- Reranking should run after merge and should be offloaded if CPU-bound.
- Each retriever should have timeout and failure policy.
- Failed optional retrievers should be visible in metrics/logs.

Acceptance:

- Current vector-only search works through `VectorRetriever`.
- BM25 can be added without editing `RagEngine` internals heavily.
- Reranking happens once after candidate merge.

### Phase 11: Generation Boundary Cleanup

Goal: decide whether this service owns answer generation or only retrieval.

Files:

```text
rag_server/engine/engine.py
rag_server/services/generation.py
rag_server/adapters/base.py
rag_server/grpc/server.py
rag_server/app.py
tests/test_phase8_generation.py
```

Actions if generation stays:

- Wire `OpenRouterClient` in `app.py` behind config.
- Use adapter `build_prompt()` instead of generic engine prompt.
- Include model, temperature, max tokens, prompt strategy, and chunk signature in response cache key.
- Preserve chunk metadata in `GenerateRequest` mapping.
- Return clear unavailable errors when generation is disabled.

Acceptance:

- Retrieval-only deployment is clean.
- Generation-enabled deployment does not crash because `_openrouter` is missing.
- Cached generation responses are not reused across different model/config settings.

### Phase 12: Version Policy Documentation Before Conflict Resolver

Goal: keep version control planned without prematurely building a complex conflict system.

Current version-related fields:

- `content_hash`
- `embedding_version`
- `chunker_version`
- `VersionManager`

Plan-only concepts:

- `document_version`
- `write_policy`
- conflict behavior for changed content

Potential write policies:

- `replace_current`: replace deterministic points for the same document identity.
- `skip_if_same_hash`: no-op when content hash already exists.
- `fail_if_changed`: reject write if existing content hash differs.
- `keep_history`: keep old raw content and index a new logical revision.

Acceptance:

- Version metadata is carried consistently.
- Conflict behavior is documented before implementation.
- `VersionManager` is refactored onto async-safe storage before it is expanded.

## 5. Updated File Work List

High-priority existing files:

```text
rag_server/app.py
rag_server/engine/engine.py
rag_server/services/embedding.py
rag_server/config/repository.py
rag_server/services/cache.py
rag_server/versioning/manager.py
rag_server/storage/filesystem.py
rag_server/gateway/handler.py
rag_server/grpc/server.py
proto/rag_service.proto
rag_server/core/models.py
rag_server/adapters/website.py
rag_server/storage/base.py
rag_server/storage/s3.py
```

Likely new files:

```text
rag_server/datatypes/__init__.py
rag_server/datatypes/base.py
rag_server/datatypes/registry.py
rag_server/jobs/__init__.py
rag_server/jobs/base.py
rag_server/jobs/sqlite.py
rag_server/retrieval/__init__.py
rag_server/retrieval/base.py
rag_server/retrieval/vector.py
rag_server/retrieval/bm25.py
rag_server/retrieval/coordinator.py
```

Dependency decision:

```text
Option A: add aiosqlite for SQLite async I/O.
Option B: keep sqlite3 but centralize DB work behind asyncio.to_thread / executor.
```

Recommendation: use `aiosqlite` unless dependency policy blocks it. It makes the async guarantee clearer and avoids repeating executor boilerplate across repositories.

## 6. Test Plan

Add or update tests for:

- App wiring uses an embedding provider with both `encode()` and `encode_batch()`.
- Search and ingest both work through the same app-created engine.
- SQLite config/cache methods do not call sync DB functions directly in async paths.
- Bounded ingest queue rejects overload.
- Durable job state survives repository re-instantiation.
- Failed ingest stores an error message.
- Search response has nonzero `elapsed_ms`.
- gRPC returns typed payload fields in `ChunkResult`.
- Gateway validates typed `visibility`.
- Search by `data_type` excludes other data types.
- Missing or blank ingest `kb_id` lands in the default KB.
- Blank search `kb_ids` are ignored instead of becoming empty-string filters.
- Raw storage key includes `project_id`, `user_id`, `kb_id`, `data_type`, `doc_id`, and `content_hash`.
- Filesystem object storage is offloaded or excluded from production app wiring.
- S3 host/canonical path signing works for `https://`, `http://`, and path-style endpoints.
- Generation disabled path returns a clear error.
- Generation enabled path includes model/config in cache key.
- Retrieval coordinator runs independent retrievers concurrently and reranks merged candidates.

## 7. Immediate Next Coding Order

1. Fix embedding provider interface and app wiring.
2. Make SQLite and filesystem persistence async-safe.
3. Fix `elapsed_ms`, ingest error/doc status, queue metrics, and ingest loop cleanup.
4. Add durable bounded ingest job repository.
5. Expose typed fields through gRPC/gateway.
6. Extend retrieval filters for `data_type`, visibility, and versions.
7. Add the retrieval framework for vector/BM25/hybrid/rerank, keeping vector as the first concrete retriever.
8. Introduce a small data-type registry so each data type can own schema, parsing, filters, and retrieval defaults.
9. Replace metadata raw content with typed raw content and collision-safe storage keys.
10. Add service-level batch ingest.
11. Make website adapter config-backed.
12. Clean up generation boundary.
13. Document version conflict policy, then implement only after product behavior is agreed.

## 8. Bottom Line

Do not restart the engine from scratch. The current base has useful pieces and several earlier plan items are already implemented.

The next work should focus on async correctness and runtime viability first:

- fix the app/embedding ingest crash,
- remove fake-async SQLite/filesystem paths,
- make ingest status durable and bounded,
- then expose the already-added base fields through the service API and retrieval filters,
- then move search behind a retriever coordinator so BM25 and hybrid search can be added without changing the engine core.

After that, batch ingest and optional generation can be added cleanly without turning the engine into a broad tenant, workflow, or permission-control platform.
