# Ingestion Generic Indexing Path

Status: accepted.

## Requirement

Ingestion workers should be generic content-preparation workers. They should
not call project-document compatibility clients after preparation. Successful
queued ingestion should complete only after prepared chunks are accepted by the
retrieval indexing capability.

## Implemented

- Removed project-document client delegation from `IngestionRequestConsumer`.
- Made enabled ingestion apps require:
  - ingestion-owned job repository
  - `IngestionService`
  - retrieval index queue
- Made standalone ingestion workers require retrieval index publication.
- Kept ingestion job completion tied to retrieval index worker response.
- Kept placement plans and retrieval config flowing through index messages.
- Removed ingestion worker project-client settings from local config and runner
  defaults.

## Remaining Work

- Replace local/SQLite queue adapters with production broker semantics.
- Add retries, leases, attempts, dead-letter topics, and repair metadata.
- Add transport-level ingestion submission API if needed outside the queue path.

## Verification

- `pytest tests/test_ingestion_service_server.py tests/test_ingestion_worker_server.py tests/test_local_split_ingestion_index_smoke.py -q`
