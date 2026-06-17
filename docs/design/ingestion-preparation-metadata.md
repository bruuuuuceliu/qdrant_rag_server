# Ingestion Preparation Metadata

Section status: implementation accepted for the third development loop section.

## Requirement Document

The ingestion queue worker now owns job acceptance, but normal queued execution
still delegates immediately to `ProjectDocumentClient.ingest`. The standalone
`IngestionService` already loads sources, routes handlers, parses content,
normalizes sections, and produces neutral chunks. The worker should start using
that ingestion-owned preparation path before compatibility execution so future
sections can publish prepared chunks to retrieval indexing without depending on
the project/RAG engine.

This section records ingestion-owned preparation metadata for queued jobs. It
does not replace indexing or the public compatibility result yet. Preparation is
optional and injected so existing embedded compatibility paths can continue to
run unchanged until their composition roots are moved.

Scope:

- Add an optional ingestion preparation service to the queue consumer.
- Convert `QueuedIngestCommand` into a project-neutral source request accepted
  by `IngestionService.process(...)`.
- When job storage is configured, update job metadata with preparation details:
  content hash, content type, handler, chunk count, raw content length, and
  chunker versions.
- Preserve compatibility execution through `ProjectDocumentClient.ingest` after
  preparation succeeds.
- Wire the standalone ingestion worker to use `IngestionService` for
  preparation.

Out of scope:

- Publishing `retrieval.index.requests`.
- Replacing `ProjectDocumentClient.ingest` as the normal execution path.
- Persisting prepared chunks to object storage.
- Changing manager, project, or public gRPC APIs.

## Acceptance Criteria

- `IngestionRequestConsumer` accepts an optional `IngestionService` instance.
- When an ingestion service and job repository are configured, the consumer
  runs ingestion preparation before delegated compatibility execution.
- Preparation updates the accepted job metadata with `content_hash`,
  `prepared_chunk_count`, `raw_content_length`, `handler_name`, `content_type`,
  and `chunker_versions`.
- The compatibility client still receives the original command request payload.
- If no ingestion service is configured, existing queue behavior is unchanged.
- The standalone ingestion worker wires an `IngestionService` into the consumer.
- Tests cover metadata updates, compatibility payload preservation, and the
  no-preparation path.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
ingestion_service/server/
  app.py             optional preparation-service injection
  consumer.py        preparation and job metadata updates
  worker.py          standalone worker preparation wiring

tests/
  test_ingestion_service_server.py
  test_ingestion_worker_server.py

docs/
  design/ingestion-preparation-metadata.md

progress.md
```

No new config is required. This section is an in-process composition change;
future sections can add config when prepared output is sent to a retrieval
indexing queue.

## Class Design

### `IngestionRequestConsumer`

New constructor dependency:

- `ingestion_service: IngestionService | None`

New behavior:

- accept job
- prepare source with `IngestionService.process(...)` when both an ingestion
  service and job repository are configured
- update job metadata from the preparation result
- delegate compatibility execution unchanged

## Implementation Design

1. Add optional `ingestion_service` injection to `IngestionRequestConsumer` and
   `ingestion_service.server.create_app`.
2. Add a private preparation method that calls `IngestionService.process(...)`
   with the command request payload.
3. Add a small metadata renderer for `IngestionResult`.
4. Update job metadata after preparation and before compatibility execution.
5. Wire `IngestionService()` into the standalone worker composition root.
6. Add tests for preparation metadata and no-preparation compatibility.
7. Run focused ingestion, manager, and shared-contract tests.

## Review Checklist

- The consumer still has no imports from project RAG engine, Qdrant, embedding,
  retrieval indexing internals, or parser-specific implementations.
- Preparation metadata is small and durable; it does not store full chunk text in
  the job table.
- The compatibility client receives the same request fields as before.
- Failed preparation fails the queued response rather than silently continuing
  with ambiguous job state.
