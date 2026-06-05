# API

The current public transport is gRPC.

Proto file:

```text
proto/rag_service.proto
```

Service:

```protobuf
service RagService {
  rpc Search(SearchRequest) returns (SearchResponse);
  rpc Ingest(IngestRequest) returns (IngestResponse);
  rpc GetIngestJobStatus(GetIngestJobStatusRequest) returns (GetIngestJobStatusResponse);
  rpc Generate(GenerateRequest) returns (GenerateResponse);
  rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);
}
```

## Search

Request:

```text
project_id
user_id
query
kb_ids
include_shared
```

Response:

```text
chunks
elapsed_ms
cache_hit
```

Chunk result:

```text
project_id
user_id
kb_id
doc_id
chunk_id
chunk_index
text
score
metadata
```

Notes:

- Clients cannot send raw Qdrant filters.
- `kb_ids` is optional.
- Empty `kb_ids` means no KB filter.
- Shared content is controlled by `include_shared`.

## Ingest

Request:

```text
project_id
user_id
kb_id
doc_id
source_uri
content_type
metadata
```

Response:

```text
job_id
status
```

Notes:

- Missing or blank `kb_id` becomes `default`.
- Current raw text convention is `metadata["raw_text"]`.
- Ingest runs in a background worker.
- The response returns a job ID for status polling.

## GetIngestJobStatus

Request:

```text
job_id
```

Response:

```text
job_id
status
error
doc_id
```

Current status is in-memory only and does not survive restart.

## Generate

Request:

```text
project_id
user_id
query
chunks
openrouter_api_key
model
```

Response:

```text
response
cache_hit
```

Notes:

- Generation is optional.
- The OpenRouter key is request-scoped.
- If generation is disabled in app wiring, gRPC returns `UNAVAILABLE`.
- Invalid or missing OpenRouter keys return authentication errors.

## HealthCheck

Request:

```text
empty
```

Response:

```text
status
components
```

Status values:

```text
healthy
degraded
unhealthy
```

## Planned API Improvements

The current proto is intentionally small but incomplete. Planned typed fields:

Ingest:

```text
data_type
visibility
content_hash
chunker_version
raw_text or raw_content
```

Search:

```text
data_types
doc_ids
embedding_versions
chunker_versions
```

ChunkResult:

```text
data_type
visibility
content_hash
embedding_version
chunker_version
```

Batch ingest:

```text
BatchIngestRequest
BatchIngestResponse
Batch status
```
