# Extension Guide

This service is designed to grow by replacing or adding small components.

## Add A Project Adapter

Implement `ProjectAdapter`.

Required methods:

```text
get_config(project_id)
build_query_scope(request)
build_retrieval_filter(scope)
parse_document(input)
build_chunks(document)
build_payload(chunk)
build_prompt(query, chunks, scope)
```

Then register the adapter:

```python
registry = ProjectAdapterRegistry()
registry.register(MyProjectAdapter())
```

And store project config with:

```text
project_id
project_type
active_embedding_version
embedding_model
reranker_model
```

The adapter should own project-specific fields. The engine should continue to use base models.

## Add A Data Type

The current code has `data_type` fields but does not yet have a data-type registry.

Target shape:

```python
class DataTypeAdapter(Protocol):
    data_type: str
    async def parse(self, request): ...
    async def chunk(self, document): ...
    async def payload(self, chunk): ...
    async def build_filter(self, request): ...
```

A data type should define:

- input schema
- validation
- parsing
- chunking
- payload fields
- filter semantics
- default retrievers
- prompt strategy if generation is used

Examples:

```text
project_document
agent_memory
running_record
case_note
support_ticket
code_symbol
```

## Add A Retriever

Vector retrieval is currently embedded in `RagEngine.search()`. The target is a retriever framework.

Suggested interface:

```python
class Retriever(Protocol):
    name: str
    async def retrieve(self, query, config, retrieval_filter): ...
```

Retriever result:

```text
payload
score
source
```

Examples:

```text
VectorRetriever
BM25Retriever
HybridRetriever
MetadataRetriever
```

The coordinator should:

- run independent retrievers concurrently
- apply timeouts
- merge and deduplicate candidates
- expose optional failures in metrics/logs
- rerank once after merge
- return top-k results

## Add Reranking

Reranking should happen after candidate merge.

Keep reranking optional:

```text
no reranker -> return top-k candidates
reranker configured -> rerank candidates then return top-k
```

CPU-bound reranking should run in an executor or worker pool.

## Replace The Embedding Provider

The engine expects a provider with:

```python
async def encode(text: str) -> list[float]: ...
async def encode_batch(texts: list[str]) -> list[list[float]]: ...
```

Any local or remote embedding implementation can be used if it satisfies this shape.

## Replace Job Status Storage

Current status is an in-memory dict.

Target protocol:

```python
class JobStatusRepository(Protocol):
    async def create(job): ...
    async def update(job_id, status, **fields): ...
    async def get(job_id): ...
```

Implementations:

- memory for tests/dev
- SQLite for local durable jobs
- external queue/state store later

## Replace Object Storage

Implement `ObjectStorage`:

```text
put(key, content, content_type)
get(key)
delete(key)
exists(key)
```

Current implementations:

- memory
- filesystem
- S3-compatible

Future storage keys should include:

```text
project_id/user_id/kb_id/data_type/doc_id/content_hash
```

## Replace Generation Client

Current generation client is OpenRouter.

Generation must remain optional. Retrieval-only deployments should work without any LLM client.

Provider keys should be supplied per request and never stored.

Any replacement client should expose a small async method such as:

```python
async def generate(prompt, api_key, model, max_tokens, temperature): ...
```

## Replace Transport

Current transport is gRPC.

Future transports can map into the same gateway request objects:

- HTTP
- queue consumer
- CLI
- internal SDK

Transport should only parse raw input and call the gateway/engine. It should not own retrieval filters or backend logic.
