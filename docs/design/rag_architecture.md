# RAG Service Architecture

## Status

Draft design.

## Purpose

This document defines the target architecture for an async, multi-tenant RAG service. The service processes raw documents, indexes chunks into Qdrant, retrieves tenant-isolated context, and supports response generation through OpenRouter using the API key provided by each request.

The architecture is project-based rather than website-specific. Website RAG is one project type implemented through child schemas and adapters.

## Goals

- Process raw documents into searchable chunks.
- Answer queries with tenant-isolated retrieval.
- Support multiple project types through reusable base models and project adapters.
- Run ingestion, retrieval, reranking, and generation orchestration asynchronously.
- Handle multiple concurrent queries and ingestion jobs.
- Keep query-time retrieval local to the engine server.
- Use OpenRouter credentials supplied per request, never a fixed global service key.

## Non-Goals

- Fetch raw documents from object storage during query-time retrieval.
- Load embedding or reranking models inside FaaS workers.
- Store OpenRouter API keys in Qdrant, SQLite, logs, caches, or cache keys.
- Couple the core engine to website-specific fields or schemas.

## Physical Architecture

One always-on engine machine, expected size: 8 GB RAM, about $20-40/month:

- Qdrant for vectors and payloads.
- BGE-base embedding model, loaded once and kept warm.
- BGE-Reranker-base model, loaded once and kept warm.
- Async RAG gateway over gRPC.
- SQLite config database at `/var/lib/rag/config.db`.
- SQLite response cache at `/var/lib/rag/response_cache.db`.

External services:

- Remote object storage, such as S3 or R2, for raw documents only.
- OpenRouter for LLM generation.
- FaaS workers for authentication, document parsing, storage orchestration, retrieval calls, OpenRouter calls, and final responses.

## Async and Concurrency Requirements

The system must be async-first.

- gRPC endpoints must be async.
- Query requests must run concurrently.
- Document ingestion jobs must run concurrently.
- Ingestion and query traffic must be able to run at the same time.
- Qdrant, SQLite, object storage, and OpenRouter calls should use async clients where available.
- CPU-bound parsing, embedding, and reranking should run in bounded worker pools if they would otherwise block the event loop.
- Expensive work must be protected by bounded queues, semaphores, or worker pools.
- Per-project and per-user limits must prevent one tenant from starving others.
- Saturated services should return backpressure errors or queue status.
- Cache access must be concurrency-safe.
- Cache invalidation must be atomic for the affected project or user scope.

## Core Data Model

Qdrant uses one collection per project per embedding version:

```text
rag_{project_id}_{embedding_version}
```

Each Qdrant point contains a vector and a payload:

```text
vector: [1536 floats]
payload: BaseChunkPayload
```

Base payload fields:

```text
BaseChunkPayload
  project_id
  user_id
  kb_id
  doc_id
  chunk_id
  chunk_index
  text
  metadata
```

Isolation rules:

- Every query must include a mandatory `project_id` and `user_id` scope.
- Retrieval filters are built and enforced by the gateway.
- Clients must not provide raw Qdrant filters directly.
- Project-wide shared content uses `user_id = "__shared__"`.
- Query-time retrieval may include both user-specific content and shared project content when allowed by policy.

## Reusable Base Models

The engine should depend on atomic base models. Project-specific fields belong in child classes.

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

## Project Adapter Interface

The core engine should call project adapters through a base interface:

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

The core engine must import and call only base models and base interfaces. It should not branch on website-specific fields directly.

## Project Registry

`config.db` stores the `project_type` for each `project_id`. At runtime, the gateway resolves the adapter from a registry:

```text
project_type = config_db.get_project_type(project_id)
adapter = project_registry.get(project_type)
```

This keeps the engine generic while allowing each project type to own its schemas, configs, validation rules, prompt rules, and payload extensions.

## Website Project Example

Website RAG is one child implementation:

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

Other project types can be added without changing the engine, such as support docs, product catalogs, internal knowledge bases, legal documents, or code documentation.

## Query Flow

Target retrieval latency: 50-300 ms.

```text
FaaS Worker                          Engine Server
    |                                     |
    |-- async gRPC: search(query, scope)->|
    |                                     |-- Resolve ProjectAdapter
    |                                     |-- Build BaseQueryScope
    |                                     |-- Build BaseRetrievalFilter
    |                                     |-- Tier 1 cache hit? return
    |                                     |-- Encode query with warm embedding model
    |                                     |-- Qdrant search with enforced filters
    |                                     |-- Re-rank top 20 with warm reranker
    |                                     |-- Return top 5 chunks
    |                                     |
    |-- Tier 2 cache hit? return          |
    |-- Build prompt                      |
    |-- OpenRouter API with request key  -> external LLM
    |-- Cache result                      |
    |-- Respond                           |
```

The engine handles retrieval. FaaS workers handle orchestration and LLM calls.

## Ingest Flow

```text
Upload
  -> Authenticate request
  -> Resolve ProjectAdapter by project_id
  -> Parse document through ProjectAdapter
  -> Store raw document in remote storage
  -> Async gRPC call to engine
  -> Build chunks through ProjectAdapter
  -> Embed chunks
  -> Build payloads through ProjectAdapter
  -> Upsert chunks into Qdrant
  -> Invalidate affected caches
```

Ingestion is asynchronous and may run in the background. Upload requests may either wait for completion or return a job ID, depending on product requirements.

Document text is stored in Qdrant payloads. Remote object storage is not used during query-time retrieval.

## Cache Strategy

Tier 1: engine memory cache.

- Maps query context to vector search results.
- Stored in memory on the engine.
- Per-project `OrderedDict`.
- 5,000 entries per project.
- 1 hour TTL.
- Lost on engine restart.
- Invalidated when documents or retrieval config change.

Tier 2: SQLite response cache.

- Maps query context to full LLM responses.
- Stored in `/var/lib/rag/response_cache.db`.
- Survives engine restart.
- Scoped by `project_id` and `user_id`.
- 1 hour TTL.
- Invalidated when documents or relevant config change.

Invalidation rules:

| Event | Tier 1 Action | Tier 2 Action |
| --- | --- | --- |
| User uploads or deletes a document | Clear that project | Clear that user |
| Chunker or model config changes | Clear that project | Clear that project |
| TTL expires | Automatic expiry | Automatic expiry |

## OpenRouter Credential Handling

OpenRouter keys are request-scoped.

- The service must not use one fixed global OpenRouter API key.
- Each query request must provide the OpenRouter API key to use for generation.
- The key is used only for the current OpenRouter call.
- The key must not be stored in Qdrant, SQLite, logs, cache keys, or cached responses.
- Cache entries should be scoped by tenant and query context, not by storing the API key.
- Requests without an OpenRouter key must fail with an authentication or configuration error when generation is required.

## Version Upgrades

For embedding model or chunker changes:

1. Create a new collection, for example `rag_project_v4`.
2. Start a background re-index job from raw documents in remote storage.
3. Atomically swap the active version in `config.db`.
4. Keep the old collection for a 7-day grace period.
5. Delete the old collection after the grace period.

This allows model and chunker changes without blocking queries or corrupting existing indexes.

## Recovery Hierarchy

| Failure Scenario | Recovery Path | Expected Time |
| --- | --- | --- |
| Qdrant restarts on the same machine | Normal process restart | About 10 seconds |
| Machine dies | Restore from snapshot on a new machine | About 2 minutes |
| Total local loss | Restore off-site snapshot from S3 or R2 | About 10 minutes |
| Snapshot unavailable or stale | Rebuild from raw documents | Hours, background job |

## Query-Time Storage Rules

Remote storage is never used at query time.

- Text comes from Qdrant payloads.
- Metadata and active version configuration come from local SQLite.
- LLM generation goes through OpenRouter with the request-provided API key.
- Remote storage is used only as the durable source for raw documents and rebuilds.

## Key Decisions

- Keep heavyweight retrieval components on one always-on machine.
- Keep FaaS workers stateless and lightweight.
- Build the service async-first.
- Keep core filters and data structures project-based and reusable.
- Make the engine depend on base models and project adapters, not website-specific classes.
- Store chunk text in Qdrant payloads to avoid query-time object storage reads.
- Enforce tenant isolation in the gateway.
- Treat OpenRouter credentials as request-scoped secrets.
- Use one Qdrant collection per project per embedding version.
- Use two cache tiers: in-memory retrieval cache and durable SQLite response cache.
- Treat remote storage as a rebuild source, not part of the online query path.
