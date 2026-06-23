# Ingestion Worker Retrieval Index Queue Wiring

Status: accepted; now required for enabled ingestion workers.

## Requirement

Make the standalone ingestion worker publish prepared chunks to the retrieval
index queue in local split-service mode without requiring tests or callers to
inject a retrieval queue manually.

The retrieval indexing worker already consumes `retrieval.index.requests`; this
section wires the standalone ingestion worker to the same queue adapter and
topic so ingestion-to-index publication works across local worker processes.

## Acceptance Criteria

- Ingestion settings include retrieval index publication controls under
  `configs/ingestion`.
- Standalone ingestion worker can build a retrieval index queue when publication
  is enabled and no queue is injected.
- Queue adapter support remains limited to local-development adapters:
  `local` and `sqlite`.
- SQLite retrieval index queue defaults can share the same DB path used by the
  manager, ingestion worker, and retrieval index worker in local split-service
  mode.
- The worker passes `retrieval_index_topic` to `create_ingestion_app(...)`.
- Publication is required for enabled ingestion workers. Disabled publication is
  rejected because compatibility project-document fallback has been removed.
- Env examples and local runner defaults expose the relevant settings.
- Focused tests cover enabled wiring, disabled wiring, invalid broker handling,
  and config loading.

## Structure Design

```text
configs/ingestion/config.py
  IngestionSettings.retrieval_index_enabled
  IngestionSettings.retrieval_index_topic
  IngestionSettings.retrieval_index_queue_broker
  IngestionSettings.retrieval_index_queue_db_path
  IngestionSettings.retrieval_index_queue_maxsize

ingestion_service/server/worker.py
  _build_retrieval_queue(...)
  create_worker_server(...) passes retrieval queue and topic

configs/ingestion/local.env.example
configs/local.env.example
examples/local/run-all.sh
```

## Class Design

No new runtime class is required. `IngestionSettings` grows typed fields for
retrieval index queue publication, and the existing
`IngestionWorkerServerContext` keeps exposing the primary request queue.

## Implementation Design

1. Extend `IngestionSettings` and `load_ingestion_settings(...)` with retrieval
   index publication settings.
2. Add `_build_retrieval_queue(settings)` in the standalone ingestion worker.
3. In `create_worker_server(...)`, if no retrieval queue is injected, require
   publication to be enabled and build one from settings.
4. Pass `retrieval_index_topic=settings.retrieval_index_topic` into
   `create_ingestion_app(...)`.
5. Add env examples and make `run-all.sh` export ingestion-side retrieval index
   defaults aligned with retrieval index worker defaults.
6. Add focused tests and update progress after verification.

## Review Notes

- This remains local-development queue wiring, not a production broker design.
- `local` queue mode only works in-process; split-service mode should use
  SQLite until a production broker adapter exists.
- Compatibility project-document callback execution has been removed from the
  ingestion worker path.
