# Workflows

This document describes how the current service performs ingest, search, delete, generation, health, and version management.

## Ingest Workflow

Current path:

```text
gRPC Ingest
  -> RagServiceServicer.Ingest
  -> RagGateway.prepare_ingest
  -> ProjectAdapterResolver.resolve
  -> adapter.get_config
  -> RagEngine.schedule_ingest
  -> background ingest worker
  -> adapter.parse_document
  -> optional raw object storage
  -> adapter.build_chunks
  -> embedding_provider.encode_batch
  -> adapter.build_payload
  -> QdrantStore.upsert
  -> cache invalidation
  -> in-memory job status update
```

### Request

Current ingest request fields:

```text
project_id
user_id
kb_id
doc_id
source_uri
content_type
metadata
```

If `kb_id` is missing or blank, the gateway normalizes it to:

```text
default
```

Raw text currently uses:

```text
metadata["raw_text"]
```

Planned behavior is a typed raw content field.

### Job Status

Current status is in memory:

```text
job_id
status
doc_id
error
created_at
updated_at
```

Statuses:

```text
pending
running
completed
failed
```

Planned behavior is a durable, replaceable job status repository.

## Search Workflow

Current path:

```text
gRPC Search
  -> RagServiceServicer.Search
  -> RagGateway.prepare_search
  -> ProjectAdapterResolver.resolve
  -> adapter.get_config
  -> adapter.build_query_scope
  -> adapter.build_retrieval_filter
  -> RagEngine.search
  -> Tier1 cache lookup
  -> embedding_provider.encode(query)
  -> build Qdrant filter
  -> QdrantStore.search
  -> optional reranker
  -> return SearchResult
```

### Search Request

Current search request fields:

```text
project_id
user_id
query
kb_ids
include_shared
```

If `kb_ids` is empty, no KB filter is added. The query can search all accessible KBs for the project/user scope.

If `include_shared` is true, search includes:

```text
user_id IN [request user_id, "__shared__"]
```

If false:

```text
user_id == request user_id
```

### Qdrant Search

Qdrant search is based on:

```text
query vector similarity
+ server-built payload filters
```

The query text is embedded. Qdrant compares that vector with stored chunk vectors using cosine distance.

Current filters enforce:

```text
project_id
user_id / __shared__
kb_id when selected
doc_id when selected internally
```

### Candidate Count And Top K

Project retrieval config can set:

```text
candidate_count
top_k
```

Default behavior:

```text
retrieve 20 candidates
return 5 chunks
```

If a reranker is configured, the engine reranks the candidate list before returning `top_k`.

### Search Result

`SearchResult` includes:

```text
chunks
elapsed_ms
cache_hit
```

Each chunk contains payload fields plus a retrieval score.

## Delete Workflow

Current path:

```text
RagEngine.delete_document
  -> QdrantStore.delete_document
  -> optional object_storage.delete
  -> cache invalidation
```

Qdrant delete is scoped by:

```text
project_id
user_id
kb_id
doc_id
```

Current raw storage delete still guesses the storage key from:

```text
project_id/user_id/doc_id
```

Planned behavior is to use durable raw metadata and a collision-safe key:

```text
project_id/user_id/kb_id/data_type/doc_id/content_hash
```

## Generation Workflow

Generation is optional.

Current path:

```text
gRPC Generate
  -> validate request OpenRouter API key
  -> RagEngine.generate
  -> Tier2 response cache lookup
  -> build prompt from chunk text
  -> OpenRouterClient.generate
  -> cache response
  -> return response
```

If generation is disabled in app wiring, the engine raises a generation-unavailable error and gRPC returns `UNAVAILABLE`.

Generation must use request-scoped API keys. Keys must not be stored in:

- logs
- Qdrant payloads
- cache keys
- cache values
- SQLite records

## Health Workflow

Current health path:

```text
gRPC HealthCheck
  -> HealthChecker.check
  -> component availability report
```

Components checked:

```text
gateway
qdrant
embedding_model
reranker_model
tier1_cache
tier2_cache
config_db
openrouter
```

Health status:

```text
healthy
degraded
unhealthy
```

## Version Workflow

The version manager stores embedding/chunker version metadata in SQLite.

Supported operations:

- create a new version row
- activate a version
- list versions
- get active version
- delete expired inactive version records

It does not currently create or delete Qdrant collections directly. It returns collection names for callers to act on.
