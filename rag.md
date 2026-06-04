# RAG Multi-Tenant Architecture

## Goal

Build an async RAG service that can process raw documents, index them, and answer user queries with tenant-isolated retrieval and LLM generation.

The service is designed around one always-on engine server, thin FaaS workers, local vector search, warm embedding/reranking models, and external LLM generation. It must handle multiple concurrent ingestion and query tasks without blocking the whole service.

## Physical Layout

One always-on machine, expected size: 8 GB RAM, about $20-40/month.

Services on the engine machine:

- Qdrant for vectors and payloads, with vectors on disk and HNSW indexes in RAM.
- BGE-base embedding model, loaded once and kept warm.
- BGE-Reranker-base model, loaded once and kept warm.
- RAG gateway over gRPC, responsible for orchestrating retrieval.
- SQLite config database at `/var/lib/rag/config.db`.
- SQLite response cache at `/var/lib/rag/response_cache.db`.

External services:

- Remote object storage, such as S3 or R2, for raw documents only.
- OpenRouter for LLM generation, using the API key supplied by each request.
- FaaS workers for authentication, document parsing, and request orchestration.

## Async and Concurrency Model

The whole system should be async-first.

Required behavior:

- Handle multiple query requests at the same time.
- Handle multiple document ingestion tasks at the same time.
- Allow ingestion and query traffic to run concurrently.
- Avoid blocking the event loop on model inference, Qdrant calls, SQLite calls, object storage calls, or OpenRouter calls.
- Use bounded queues, semaphores, or worker pools for expensive tasks such as embedding, reranking, and document parsing.
- Apply per-project and per-user concurrency limits so one tenant cannot starve others.
- Return backpressure errors or queue status when the engine is saturated.

Implementation expectations:

- gRPC endpoints should be async.
- Qdrant, SQLite, object storage, and OpenRouter clients should use async APIs where available.
- CPU-bound parsing or model inference should run in dedicated worker pools if the runtime would otherwise block.
- Cache access must be concurrency-safe.
- Cache invalidation must be atomic for the affected project or user scope.

## Data Model

Qdrant uses one collection per project per embedding version:

```text
rag_{project_id}_{embedding_version}
```

Each point contains:

```text
vector: [1536 floats]
payload: {
  project_id,
  user_id,
  kb_id,
  doc_id,
  text,
  chunk_index,
  ...
}
```

Isolation rules:

- Every query must include a mandatory `project_id` and `user_id` filter.
- Filters are enforced by the gateway, never trusted from the client.
- Project-wide shared knowledge uses `user_id = "__shared__"`.
- Query-time retrieval may include both user-specific content and shared project content when allowed by policy.

## Core Abstraction Model

The RAG engine should be reusable across different project types. The core service should call only base models and base interfaces. Project-specific schemas, filter rules, config defaults, and payload extensions should live in child classes.

### Base Models

The engine should depend on atomic base models like these:

```text
BaseProjectConfig
  project_id
  project_type
  active_embedding_version
  embedding_model
  reranker_model
  chunker_config
  retrieval_config
  cache_config

BaseQueryScope
  project_id
  user_id
  kb_ids
  include_shared

BaseRetrievalFilter
  project_id
  user_id
  kb_ids
  doc_ids
  shared_user_id

BaseDocument
  project_id
  user_id
  kb_id
  doc_id
  source_uri
  content_type
  metadata

BaseChunk
  project_id
  user_id
  kb_id
  doc_id
  chunk_id
  chunk_index
  text
  metadata

BaseChunkPayload
  project_id
  user_id
  kb_id
  doc_id
  chunk_id
  chunk_index
  text
  metadata

BaseIngestJob
  project_id
  user_id
  doc_id
  source_uri
  status
  error

BaseCacheScope
  project_id
  user_id
  query_hash
  config_version
```

### Base Interfaces

Core retrieval and ingestion should call interfaces instead of concrete project implementations:

```text
ProjectAdapter
  get_config(project_id) -> BaseProjectConfig
  build_query_scope(request) -> BaseQueryScope
  build_retrieval_filter(scope) -> BaseRetrievalFilter
  parse_document(input) -> BaseDocument
  build_chunks(document) -> list[BaseChunk]
  build_payload(chunk) -> BaseChunkPayload
  build_prompt(query, chunks, scope) -> prompt
```

The core code should import and call these base models and interfaces only. It should not branch on website-specific fields directly.

### Project Registry

`config.db` should store the `project_type` for each `project_id`. At runtime, the gateway resolves the adapter from a registry:

```text
project_type = config_db.get_project_type(project_id)
adapter = project_registry.get(project_type)
```

This keeps the engine generic while allowing each project type to own its schemas, configs, validation rules, prompt rules, and payload extensions.

The engine pipeline should only know these base shapes:

```text
request
  -> resolve ProjectAdapter by project_id
  -> ProjectAdapter.build_query_scope
  -> ProjectAdapter.build_retrieval_filter
  -> embed query
  -> Qdrant search
  -> rerank
  -> ProjectAdapter.build_prompt
  -> generation
```

### Website Project Child Classes

A website RAG project is one child implementation of the base model:

```text
WebsiteProjectConfig extends BaseProjectConfig
  domains
  crawl_rules
  sitemap_urls
  default_locale

WebsiteDocument extends BaseDocument
  url
  canonical_url
  page_title
  page_description

WebsiteChunkPayload extends BaseChunkPayload
  url
  canonical_url
  page_title
  section_heading

WebsiteProjectAdapter extends ProjectAdapter
  validates allowed domains
  maps website URLs into document metadata
  adds website-specific Qdrant payload fields
  builds website-specific prompts
```

Other project types can add their own child classes without changing the engine:

- Support docs project.
- Product catalog project.
- Internal knowledge base project.
- Legal document project.
- Code documentation project.

## Query Flow

Target latency for retrieval: 50-300 ms.

```text
FaaS Worker                         Engine Server
    |                                    |
    |-- async gRPC: search(query, scope)->|
    |                                    |-- Tier 1 cache hit? return
    |                                    |-- Encode query with warm embedding model
    |                                    |-- Qdrant search with enforced tenant filters
    |                                    |-- Re-rank top 20 with warm reranker
    |                                    |-- Return top 5 chunks
    |                                    |
    |-- Tier 2 cache hit? return         |
    |-- Build prompt                     |
    |-- OpenRouter API with request key -> external LLM
    |-- Cache result                     |
    |-- Respond                          |
```

The engine handles retrieval. FaaS workers handle orchestration and LLM calls.

## Cache Strategy

### Tier 1: Engine Memory Cache

Purpose: cache query-to-vector-search results.

- Stored in memory on the engine.
- Per-project `OrderedDict`.
- 5,000 entries per project.
- 1 hour TTL.
- Lost on engine restart.
- Invalidated when documents change.

### Tier 2: SQLite Response Cache

Purpose: cache query-to-full-LLM-response results.

- Stored on disk in `/var/lib/rag/response_cache.db`.
- Survives engine restart.
- Scoped by `project_id` and `user_id`.
- 1 hour TTL.
- Invalidated when documents or relevant config change.

## Cache Invalidation

| Event | Tier 1 Action | Tier 2 Action |
| --- | --- | --- |
| User uploads or deletes a document | Clear that project | Clear that user |
| Chunker or model config changes | Clear that project | Clear that project |
| TTL expires | Automatic expiry | Automatic expiry |

## Ingest Flow

```text
Upload
  -> Resolve ProjectAdapter by project_id
  -> FaaS parses document through ProjectAdapter
  -> Store raw document in remote storage
  -> Async gRPC call to engine
  -> Engine builds chunks through ProjectAdapter
  -> Engine embeds chunks
  -> Engine builds payloads through ProjectAdapter
  -> Engine upserts chunks into Qdrant
  -> Engine invalidates affected caches
```

Document text is stored in the Qdrant payload. Remote storage is not used during query-time retrieval.

Ingestion is asynchronous and can run in the background. Upload requests may either wait for completion or return a job ID, depending on product requirements.

## FaaS Worker Responsibilities

FaaS workers are thin routers with about 200 ms cold start.

Responsibilities:

- Authenticate requests.
- Parse uploaded documents.
- Store raw documents in remote storage.
- Call the engine over gRPC.
- Call OpenRouter for generation using the API key provided by the current request.
- Return the final response.

FaaS workers do not load embedding models, reranking models, or vector indexes.

## OpenRouter Credential Handling

OpenRouter keys are request-scoped.

Rules:

- The service must not use one fixed global OpenRouter API key.
- Each query request must provide the OpenRouter API key to use for generation.
- The key is used only for the current OpenRouter call.
- The key must not be stored in Qdrant, SQLite, logs, cache keys, or cached responses.
- Cache entries should be scoped by tenant and query context, not by storing the API key.
- If no OpenRouter key is provided, the service should reject generation requests with an authentication or configuration error.

## Recovery Hierarchy

| Failure Scenario | Recovery Path | Expected Time |
| --- | --- | --- |
| Qdrant restarts on the same machine | Normal process restart | About 10 seconds |
| Machine dies | Restore from snapshot on a new machine | About 2 minutes |
| Total local loss | Restore off-site snapshot from S3 or R2 | About 10 minutes |
| Snapshot unavailable or stale | Rebuild from raw documents | Hours, background job |

## Version Upgrades

For embedding model or chunker changes:

1. Create a new collection, for example `rag_project_v4`.
2. Start a background re-index job from raw documents in remote storage.
3. Atomically swap the active version in `config.db`.
4. Keep the old collection for a 7-day grace period.
5. Delete the old collection after the grace period.

This allows model and chunker changes without blocking queries or corrupting existing indexes.

## Query-Time Storage Rules

Remote storage is never used at query time.

At query time:

- Text comes from Qdrant payloads.
- Metadata and active version configuration come from local SQLite.
- LLM generation goes through OpenRouter with the request-provided API key.

Remote storage is used only as the durable source for raw documents and rebuilds.

## Key Design Decisions

- Keep heavyweight retrieval components on one always-on machine.
- Keep FaaS workers stateless and lightweight.
- Build the service async-first so ingestion, retrieval, and generation can run concurrently.
- Keep core filters and data structures project-based and reusable.
- Make the engine depend on base models and project adapters, not website-specific classes.
- Store chunk text in Qdrant payloads to avoid query-time object storage reads.
- Enforce tenant isolation in the gateway.
- Treat OpenRouter credentials as request-scoped secrets, never fixed service configuration.
- Use one Qdrant collection per project per embedding version.
- Use two cache tiers: in-memory retrieval cache and durable SQLite response cache.
- Treat remote storage as a rebuild source, not part of the online query path.
