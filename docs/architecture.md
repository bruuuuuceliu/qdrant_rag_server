# Architecture

The service is intentionally layered. Each layer should have a narrow job and be replaceable.

## High-Level Flow

```text
client / worker
  -> transport
  -> gateway
  -> adapter resolution
  -> engine
  -> retriever / storage / cache / status services
  -> response
```

## Layers

```text
proto/              gRPC protobuf definition
rag_server/grpc/    async gRPC transport
rag_server/gateway/ request validation, defaults, scope, concurrency limits
rag_server/adapters project and data parsing/chunking/payload behavior
rag_server/core/    shared model objects
rag_server/engine/  orchestration for search, ingest, delete, generation
rag_server/services embeddings, vector store, reranker, cache, generation
rag_server/storage/ raw source object storage abstractions
rag_server/config/  project configuration repository
rag_server/health/  health checks and metrics
rag_server/versioning/ embedding collection version metadata
```

Future packages likely needed:

```text
rag_server/retrieval/ vector, BM25, hybrid, metadata retrievers
rag_server/jobs/      durable ingest job repositories
rag_server/datatypes/ data-type registry and schemas
```

## Component Responsibilities

### Transport

Current transport is gRPC. It maps protobuf request objects into gateway request objects.

Transport should not build raw Qdrant filters or own retrieval logic.

### Gateway

The gateway validates request shape and builds safe retrieval intent.

Responsibilities:

- validate required request fields
- normalize defaults such as `kb_id = "default"`
- reject raw client-supplied Qdrant filters
- resolve project adapters
- build `BaseQueryScope`
- build `BaseRetrievalFilter`
- enforce simple concurrency limits

### Adapter

Adapters convert project-specific or data-type-specific input into common retrieval records.

Current adapter:

```text
WebsiteProjectAdapter
```

Adapter responsibilities:

- load project config
- parse ingest input into `BaseDocument`
- chunk documents into `BaseChunk`
- build `BaseChunkPayload`
- build retrieval scope/filter hooks
- optionally build prompts for generation

### Engine

The engine orchestrates work. It should not own project-specific parsing or transport-specific request handling.

Current engine responsibilities:

- search
- schedule and run ingest jobs
- delete documents
- fetch raw documents from object storage
- optional generation
- cache invalidation
- metrics updates

### Services

Services are replaceable implementation details:

- `EmbeddingService`: async-safe sentence-transformer wrapper
- `QdrantStore`: async Qdrant wrapper
- `RerankerService`: async-safe reranker wrapper
- `Tier1MemoryCache`: in-memory retrieval cache
- `Tier2ResponseCache`: SQLite response cache
- `OpenRouterClient`: optional generation client

### Storage

Object storage is for raw source durability and rebuilds. Query-time retrieval reads text from Qdrant payloads, not object storage.

Implementations:

- memory
- filesystem
- S3-compatible

### Health And Metrics

Health reports component availability. Metrics track simple counters such as search requests, cache hits, latency, ingest jobs, failures, and queue depth.

## Replaceable Component Targets

```text
request reader       gRPC today; future HTTP, queue, CLI, SDK
gateway              validation and normalization
adapter              project/data parsing and payload construction
retriever            vector, BM25, hybrid, metadata, future methods
reranker             optional candidate reranking
embedding provider   any provider with encode/encode_batch
job status repo      memory, SQLite, external store
object storage       memory, filesystem, S3-compatible
generation client    OpenRouter or another request-scoped provider
config repo          SQLite now, other sources later
```

## Design Rules

- The engine orchestrates; it does not parse documents directly.
- The gateway validates request intent; it does not expose raw backend filters.
- Adapters own data-specific parsing and payload fields.
- Retrievers own retrieval method details.
- Optional components must have clear disabled behavior.
- User/provider keys are request-scoped and must not be stored.
