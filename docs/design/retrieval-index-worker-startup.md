# Retrieval Index Worker Startup

Status: accepted.

## Requirement

Allow retrieval indexing to run as a standalone local worker process that
consumes `retrieval.index.requests` from the configured queue and delegates to
`IndexingService`.

This section does not introduce a production broker or change the indexing
command contract. It makes the existing retrieval indexing app context runnable
outside the manager/project compatibility process so local split-service
development can exercise ingestion-to-index publication across process
boundaries.

## Acceptance Criteria

- A standalone module starts the retrieval indexing worker with
  `python -m retrieval_service.indexing.worker`.
- Worker settings load from `./configs/retrieval` and environment variables.
- The worker supports the existing local-development queue adapters:
  `local` and `sqlite`.
- SQLite queue mode uses the same queue database path as manager/ingestion when
  configured for local split-service development.
- The worker constructs retrieval-owned indexing dependencies and starts
  `RetrievalIndexConsumer` through `retrieval_service.indexing.create_app(...)`.
- The worker shuts down embedding, sparse, NER, Qdrant, and queue consumer
  resources cleanly.
- `examples/local/run-all.sh --split-services` can start the retrieval index
  worker, and `examples/local/stop-all.sh` can stop it.
- Local runner docs list the retrieval index worker log and process.
- Focused tests cover settings loading, queue selection, dependency
  composition, and local runner script references.

## Structure Design

```text
configs/retrieval/config.py
  RetrievalIndexWorkerSettings
  load_retrieval_index_worker_settings(...)

retrieval_service/indexing/worker.py
  RetrievalIndexWorkerServerContext
  create_worker_server(...)
  serve_forever(...)
  main()

examples/local/run-all.sh
  starts retrieval indexing worker in split-service mode

examples/local/stop-all.sh
  stops retrieval indexing worker from PID file and fallback process matching

tests/test_retrieval_index_worker.py
tests/test_app_config.py
```

## Class Design

### `RetrievalIndexWorkerSettings`

Fields:

- `enabled`
- `service_name`
- `request_topic`
- `queue_broker`
- `queue_db_path`
- `queue_maxsize`

### `RetrievalIndexWorkerServerContext`

Fields:

- `index_app`
- `queue`
- `indexing_service`
- `settings`
- owned dependency references for shutdown

Method:

- `shutdown()` stops the queue consumer first, then closes owned retrieval
  resources in reverse dependency order.

## Implementation Design

1. Add retrieval index worker settings to `configs/retrieval/config.py`.
2. Add `retrieval_service.indexing.worker` with small factory helpers for queue,
   embedding provider, Qdrant store, sparse encoder/index, NER, and
   `IndexingService`.
3. Keep factory helpers injectable through optional keyword arguments so focused
   tests do not need Qdrant or model downloads.
4. Use `RetrievalIndexAppContext` for consumer lifecycle instead of duplicating
   queue-consumer logic.
5. Wire `examples/local/run-all.sh --split-services` to start the worker using
   SQLite queue settings shared with ingestion publication.
6. Wire `examples/local/stop-all.sh` to stop the worker by PID and fallback
   process matching.
7. Update local runner docs and progress after focused and full verification.

## Review Notes

- The worker remains local-development infrastructure; production retry and
  dead-letter semantics are still owned by the future broker-adapter section.
- This section does not change `RetrievalIndexCommand` payloads or ingestion
  publication behavior.
- The worker builds retrieval-owned dependencies directly; project service is
  not part of the indexing worker runtime.
