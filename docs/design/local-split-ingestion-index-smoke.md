# Local Split Ingestion Index Smoke

Status: accepted.

## Requirement

Add a lightweight smoke test proving the local split-service ingestion-to-index
path works through SQLite queue instances that share the same database file.

The test should exercise manager-shaped ingest request publication, standalone
ingestion consumption and preparation, retrieval index request publication, and
retrieval index worker consumption without requiring a live manager process,
Qdrant, embedding model downloads, or network services.

## Acceptance Criteria

- The smoke test uses separate `SQLiteQueueBroker` instances for the ingestion
  side and retrieval indexing side.
- The ingestion app consumes an `ingestion.requests` message and publishes a
  `retrieval.index.requests` message to the shared SQLite queue database.
- The retrieval index consumer consumes that message from its own broker
  instance and calls the indexing service.
- The original ingestion response remains successful and preserves the accepted
  ingestion job ID.
- The indexed request contains the expected collection name, job ID, and chunk
  text.
- The test uses fakes for project-document ingest and indexing; no Qdrant,
  embedding provider, or model download is required.

## Structure Design

```text
tests/test_local_split_ingestion_index_smoke.py
  LocalSplitIngestionIndexSmokeTest
```

## Class Design

Test fakes only:

- `_FakeProjectDocuments.ingest(...)` returns a pending accepted job result.
- `_FakeIndexingService.index_chunks(...)` records the retrieval index request
  and returns a simple chunk-count result.

## Implementation Design

1. Create a temporary SQLite queue database.
2. Create separate SQLite brokers for manager/ingestion and retrieval worker
   perspectives.
3. Start `ingestion_service.server.create_app(...)` with an ingestion broker
   and a retrieval broker pointing at the same DB.
4. Start `RetrievalIndexConsumer` with its own broker instance and fake indexing
   service.
5. Publish one ingest request with raw text and collection metadata.
6. Assert the ingestion response is successful.
7. Assert the indexing service receives one request with the expected payload.
8. Stop both consumers in cleanup.

## Review Notes

- This is not a live process smoke test; it isolates the queue handoff and
  consumer behavior that the local runner now wires together.
- Full process startup remains a later manual or integration-test concern
  because it requires runtime dependencies such as Qdrant and embedding models.
