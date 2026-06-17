# Ingestion To Retrieval Index Publication

Section status: implementation accepted for the fifth development loop section.

## Requirement Document

Ingestion now owns job acceptance and preparation metadata, and the retrieval
service now owns an indexing queue consumer. The missing link is that the
ingestion worker still does not publish prepared chunks into
`retrieval.index.requests`. Until that link exists, prepared ingestion output is
not flowing through the retrieval-owned async boundary.

This section publishes prepared chunks from the ingestion consumer to the
retrieval indexing queue while preserving the current compatibility response
path. The publication should happen only after preparation succeeds and should
remain optional so local embedded compatibility runs can continue without the
retrieval queue.

Scope:

- Add optional retrieval indexing queue injection to the ingestion consumer.
- Build a neutral retrieval indexing command from prepared ingestion output.
- Publish prepared chunks to `retrieval.index.requests` when the queue is
  configured.
- Preserve the existing compatibility `ProjectDocumentClient.ingest` response
  path.
- Keep all config and environment behavior unchanged for this section.

Out of scope:

- Making indexing completion authoritative for ingest completion.
- Updating manager status to reflect retrieval indexing completion.
- Adding retry, dead-letter, or broker claim semantics.
- Replacing compatibility project-document execution.

## Acceptance Criteria

- `IngestionRequestConsumer` accepts an optional retrieval queue or publisher
  dependency.
- Prepared ingestion results are converted into a retrieval indexing command
  with collection name, neutral chunks, retrieval payloads, retrieval config,
  and job ID.
- When the retrieval queue is configured, the consumer publishes the indexing
  command to `retrieval.index.requests`.
- The retrieval indexing command contains the prepared chunks produced by
  `IngestionService.process(...)`.
- The compatibility project-document ingest response still works as before.
- Tests cover command construction, queue publication, and the no-queue path.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
ingestion_service/server/
  app.py             retrieval queue injection
  consumer.py        prepared chunk publication
  worker.py          retrieval queue wiring

tests/
  test_ingestion_service_server.py
  test_ingestion_worker_server.py

docs/
  design/ingestion-to-retrieval-index-publication.md

progress.md
```

No new config file is required yet. The queue and topic are injected from the
composition root and remain easy to replace later.

## Class Design

### `IngestionRequestConsumer`

New constructor dependency:

- `retrieval_queue: QueueBroker | None`

New behavior:

- convert `IngestionService.process(...)` output into a retrieval indexing
  command
- publish the indexing command when a retrieval queue is configured

### `RetrievalIndexCommand`

The command already exists in `retrieval_service.indexing.commands`. This
section uses it as the queue payload format rather than inventing a second
publication shape.

## Implementation Design

1. Add optional retrieval queue injection to the ingestion consumer and app
   factory.
2. Build a retrieval indexing command from the prepared ingestion result.
3. Publish the command to `retrieval.index.requests` before legacy compatibility
   response publication completes.
4. Wire the standalone ingestion worker to pass a retrieval queue when one is
   available.
5. Add tests for indexing publication and compatibility-only behavior.
6. Run ingestion, retrieval-index, and manager focused tests.

## Review Checklist

- The ingestion consumer only publishes neutral prepared chunks and retrieval
  payloads; it does not embed retrieval indexing internals.
- Publication is optional and does not break local compatibility execution.
- The queue payload remains serializable and transport neutral.
- The compatibility result still uses the project-document client until the next
  service-extraction step.
