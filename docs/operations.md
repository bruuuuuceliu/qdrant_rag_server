# Operations Runbook

This runbook covers the broker-first local/production-equivalent shape.

## Start

- For local parity, use `examples/local/run-all.sh --broker-first`.
- For an infrastructure-only gate, use `examples/local/run-all.sh --infra-only`.
- The broker-first runner starts or verifies Docker Redpanda, Redis, Qdrant,
  manager, task manager, project domain, workflow log, ingestion helper,
  retrieval helper, retrieval-index helper, storage node, and SQLite node.
- The runner bootstraps Redpanda topics with
  `broker_service.bootstrap.bootstrap_topics` and verifies Redis task-status
  read/write with TTL before starting service processes.
- The runner calls `python -m deployment.composition.readiness` before service
  startup and again after Qdrant is reachable. Use `--skip-qdrant` only for the
  infra-only broker/Redis gate.
- To validate live infrastructure outside the runner, use:
  `examples/local/run-all.sh --infra-only`, then
  `RAG_LIVE_INFRA=1 pytest -m live_infra tests/integration/test_live_infra_smoke.py -q`.

## Readiness

- Broker readiness requires the canonical topic set from `shared.contracts.TOPICS`.
- Broker readiness details include `ok`, `topics`, `bootstrap_servers`,
  `topic_prefix`, `required_topic_count`, `missing_topics`, and, when configured,
  `lag` or `lag_error`.
- Optional broker lag probes use `BROKER_LAG_TARGETS` in
  `group_id:topic,topic;group_id:topic` format. Lag probe failures are reported
  in broker readiness details and do not fail startup when required topics are
  healthy.
- Redis readiness requires `PING`, task-status write/read, and positive TTL for
  completed task status records.
- Storage and SQLite readiness require owned local roots to be writable and
  allocatable. SQLite readiness also initializes `_sqlite_node.db`, allocates a
  readiness database, records a schema version, and stores a health snapshot in
  the node control-plane tables.
- Qdrant readiness checks the configured `/collections` endpoint.
- Manager readiness requires Redpanda task publishing and Redis task-status access.
- Task manager readiness requires task-intake, domain-result, helper-result topics,
  Redis task-status access, and its durable task-state repository.
- Domain/helper/node readiness uses each worker context `health()` payload:
  `service`, `ready`, `dependencies`, and `details`.

## Troubleshooting

- Check `.run/logs/*.log` for process startup failures.
- Run `examples/local/stop-all.sh --clean` before restarting a local topology.
- Validate config with `configs.validation.validate_settings_or_raise`.
- Inspect SQLite ownership state in `_sqlite_node.db` under
  `SQLITE_NODE_DATABASE_ROOT`; service-owned rows remain in their separate
  allocated database files.
- If tasks stay `running`, inspect task-manager logs and the expected helper
  result topics for missing fan-in results. Durable fan-in state is stored at
  `TASK_MANAGER_STATE_DB_PATH`.
- Terminal helper failures publish repair context to `task.dead_letters` by
  default. Retryable helper failures are republished until
  `TASK_MANAGER_MAX_ATTEMPTS`.
- The broker service owns Redpanda transport, topic bootstrap, health, and lag
  visibility. Task leases, retries, backoff, attempt counts, and dead-letter
  decisions remain task-manager responsibilities.
