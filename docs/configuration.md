# Configuration

The app reads environment variables through `AppSettings.from_env()`.

Example file:

```text
.env.example
```

## Environment Variables

### Databases

```text
RAG_CONFIG_DB_PATH=/var/lib/rag/config.db
RAG_RESPONSE_CACHE_DB_PATH=/var/lib/rag/response_cache.db
```

`RAG_CONFIG_DB_PATH` stores project configuration.

`RAG_RESPONSE_CACHE_DB_PATH` stores cached generation responses.

Current caveat: SQLite calls are async-shaped but still blocking internally. The next implementation phase should move to `aiosqlite` or a shared executor-backed database runner.

### gRPC

```text
RAG_GRPC_PORT=50051
```

The local app starts an async gRPC server on this port.

### Qdrant

```text
RAG_QDRANT_HOST=localhost
RAG_QDRANT_PORT=6333
RAG_QDRANT_URL=http://localhost:6333
```

If `RAG_QDRANT_URL` is set, it takes priority over host/port.

### Concurrency

```text
RAG_MAX_PER_PROJECT=20
RAG_MAX_PER_USER=5
RAG_INGEST_WORKERS=4
```

Current gateway concurrency limits protect plan preparation. Engine-level semaphores and bounded ingest queues are still planned.

### Embeddings

```text
RAG_EMBEDDING_PROVIDER=local
RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RAG_EMBEDDING_DEVICE=cpu
RAG_EMBEDDING_DIMENSION=768
RAG_EMBEDDING_API_KEY=
RAG_EMBEDDING_BASE_URL=https://openrouter.ai/api/v1/embeddings
```

Provider choices:

```text
local       local sentence-transformers provider
openrouter  remote OpenAI-compatible embeddings endpoint, defaulting to OpenRouter URL
remote      remote OpenAI-compatible embeddings endpoint
```

The local embedding service loads one model instance and keeps it warm. CPU-bound model work is offloaded to a thread pool.

Remote embedding providers avoid local CPU/CUDA model calculation. They use an OpenAI-compatible embeddings request shape:

```json
{
  "model": "model-name",
  "input": ["text one", "text two"]
}
```

The response must contain:

```json
{
  "data": [
    {"embedding": [0.1, 0.2]}
  ]
}
```

`RAG_EMBEDDING_DIMENSION` must match the selected embedding model because Qdrant collections are created with that vector size.

For remote providers, set:

```bash
export RAG_EMBEDDING_PROVIDER=openrouter
export RAG_EMBEDDING_API_KEY=sk-or-your-key
export RAG_EMBEDDING_MODEL=your-embedding-model
export RAG_EMBEDDING_DIMENSION=1536
```

### Generation

```text
RAG_GENERATION_ENABLED=false
```

Generation is optional and disabled by default.

When enabled, the service creates an OpenRouter client. The actual OpenRouter API key is supplied per request through `GenerateRequest.openrouter_api_key`.

The service should not store provider keys in logs, Qdrant payloads, caches, or SQLite records.

## Project Configuration

Project config is stored in SQLite and maps project IDs to project types and model/config values.

Current stored fields:

```text
project_id
project_type
active_embedding_version
embedding_model
reranker_model
chunker_config_json
retrieval_config_json
cache_config_json
```

Planned fields:

```text
adapter_config
enabled_retrievers
retriever weights
data-type config
generation config defaults
resource limits
```

## Retrieval Configuration

Current engine config reads:

```text
candidate_count
top_k
```

Defaults:

```text
candidate_count = 20
top_k = 5
```

Future retriever config should define:

```text
retrievers = ["vector", "bm25"]
weights = {"vector": 0.7, "bm25": 0.3}
timeouts
failure policy
reranker settings
```

## Cache Configuration

Current defaults:

```text
Tier 1 retrieval cache: in-memory, per-project, 1 hour TTL
Tier 2 response cache: SQLite, per-project/user, 1 hour TTL
```

Generation cache keys should be expanded to include model, temperature, max tokens, prompt strategy, and chunk signature.
