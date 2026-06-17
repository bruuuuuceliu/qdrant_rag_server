# Retrieval Index Queue Worker

Section status: implementation accepted for the fourth development loop section.

## Requirement Document

The retrieval service owns indexing internals through `IndexingService`, but no
retrieval-owned worker consumes asynchronous indexing requests. Ingestion
preparation can now produce neutral chunks and metadata, so the next boundary is
to define the retrieval indexing queue command and provide a worker that invokes
the existing indexing facade.

This section adds a minimal queue worker shell for `retrieval.index.requests`.
It is intentionally local and dependency-injected. It does not yet wire
ingestion to publish real prepared chunks, because collection planning and
retrieval configuration still need a project-policy handoff.

Scope:

- Add a retrieval indexing queue command DTO in `retrieval_service.indexing`.
- Add a queue consumer that parses command payloads and calls
  `IndexingService.index_chunks(...)`.
- Publish a response envelope to the command response topic when one is
  provided.
- Keep worker construction dependency-injected for tests and future server
  wiring.

Out of scope:

- Ingestion publishing `retrieval.index.requests`.
- Project config/scope lookup for collection names.
- Retry, dead-letter, visibility timeout, or production broker semantics.
- Creating a retrieval indexing server process.

## Acceptance Criteria

- A `RetrievalIndexCommand` parses `collection_name`, `chunks`, `payloads`,
  `retrieval_config`, `job_id`, `request_id`, and optional `response_topic`.
- The command converts serialized chunks/payloads into neutral retrieval schema
  objects accepted by `IndexingService`.
- `RetrievalIndexConsumer` consumes `retrieval.index.requests` and calls
  `IndexingService.index_chunks(...)`.
- Successful processing publishes `{request_id, ok, result}` when a response
  topic is supplied.
- Failed processing publishes `{request_id, ok: false, error}` when a response
  topic is supplied.
- Tests cover command parsing, successful worker invocation, and failure
  response behavior.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
retrieval_service/indexing/
  commands.py        queue command DTO and parsers
  consumer.py        retrieval indexing queue consumer
  __init__.py        public exports

tests/
  test_retrieval_index_consumer.py

docs/
  design/retrieval-index-queue-worker.md

progress.md
```

## Class Design

### `RetrievalIndexCommand`

Fields:

- `request_id`
- `response_topic`
- `job_id`
- `collection_name`
- `chunks`
- `payloads`
- `retrieval_config`

Methods:

- `from_payload(payload, fallback_request_id) -> RetrievalIndexCommand`
- `to_index_request() -> IndexChunksRequest`

### `RetrievalIndexConsumer`

Constructor dependencies:

- `queue: QueueBroker`
- `indexing_service: IndexingService`
- `topic: str = "retrieval.index.requests"`

Runtime behavior:

- consume one message
- acknowledge the queue topic
- run indexing asynchronously
- publish optional success/failure response

## Implementation Design

1. Add command parsing from dict payloads using `BaseChunk` and
   `BaseChunkPayload`.
2. Add consumer start/stop and message processing logic matching the existing
   ingestion consumer style.
3. Serialize `IndexChunksResult` into a response dict.
4. Add focused command and consumer tests.
5. Run retrieval indexing, queue, and manager/ingestion focused tests.

## Review Checklist

- The worker imports retrieval indexing/schema code only; it does not import
  manager, project gateway, ingestion handlers, or Qdrant setup internals.
- Command parsing keeps retrieval config opaque to the queue layer.
- Empty chunk lists remain valid and are delegated to `IndexingService`.
- Response publishing is optional so fire-and-forget indexing remains possible.
