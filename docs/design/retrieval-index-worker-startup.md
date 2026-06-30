# Retrieval Index Worker Startup

Status: accepted.

## Requirement

Allow retrieval indexing to run as a standalone worker process that consumes
broker helper commands and delegates to `IndexingService`.

This section makes retrieval indexing runnable outside manager/project
compatibility code so local development can exercise task-service-issued helper
commands across process boundaries.

## Acceptance Criteria

- A standalone module starts the retrieval indexing worker with
  `python -m retrieval_service.indexing.worker`.
- Worker settings load from `./configs/retrieval` and environment variables.
- The worker consumes the configured retrieval-index helper command topic.
- The worker constructs retrieval-owned indexing dependencies and starts a
  broker helper app.
- The worker shuts down embedding, sparse, NER, Qdrant, and broker helper
  resources cleanly.
- `examples/local/run-all.sh` starts the retrieval index worker, and
  `examples/local/stop-all.sh` can stop it.
- Local runner docs list the retrieval index worker log and process.
- Focused tests cover settings loading, dependency composition, and local
  runner script references.

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
  starts retrieval indexing worker

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
- `command_topic`

### `RetrievalIndexWorkerServerContext`

Fields:

- `helper_app`
- `indexing_service`
- `settings`
- owned dependency references for shutdown

Method:

- `shutdown()` stops the broker helper first, then closes owned retrieval
  resources in reverse dependency order.

## Implementation Design

1. Add retrieval index worker settings to `configs/retrieval/config.py`.
2. Add `retrieval_service.indexing.worker` with small factory helpers for
   embedding provider, Qdrant store, sparse encoder/index, NER, and
   `IndexingService`.
3. Keep factory helpers injectable through optional keyword arguments so focused
   tests do not need Qdrant or model downloads.
4. Use the retrieval index helper app for broker consumer lifecycle.
5. Wire `examples/local/run-all.sh` to start the worker.
6. Wire `examples/local/stop-all.sh` to stop the worker by PID and fallback
   process matching.
7. Update local runner docs and progress after focused and full verification.

## Review Notes

- Retry and dead-letter semantics are still task-service responsibilities.
- This section does not change `RetrievalIndexCommand` payloads.
- The worker builds retrieval-owned dependencies directly; project service is
  not part of the indexing worker runtime.
