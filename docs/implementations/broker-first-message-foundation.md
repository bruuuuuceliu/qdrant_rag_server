# Broker-First Message Foundation

This note records the implemented message-path foundation. It does not replace
the architecture or development rules.

## Implemented Code

- `shared.contracts.messages`: message envelope, message types, validation, and
  producer/consumer protocols.
- `shared.contracts.topics`: canonical topic names and domain topic routing.
- `broker_service`: independent broker workspace with Redpanda settings and a
  Kafka-compatible envelope codec/adapter shell.
- `manager_service.service`: optional task-intake publication path through an
  injected message producer and task-status lookup through the shared
  task-status store contract.
- `manager_service.server.app`: manager app can be composed with task producer
  and status store instead of a project client for broker-first runtime.
- `task_manager_service`: dispatcher and server context for task intake,
  `task.requests` publication, task event/result consumption, and
  shared-contract status updates.
- `task_service`: executor dispatcher, project plan request/result handling,
  helper command dispatch, helper-result fan-in, retries/dead letters,
  explicit SQLite execution/step/attempt/result state, and final task-result
  publication.
- `project_service.domain_handler`: project-domain command handler that returns
  project plan/info results without dispatching helper work.
- `ingestion_service.server.domain_handler`: ingestion helper command handler.
- `retrieval_service.server.domain_handler`: retrieval helper command handler.
- `workflow_log_service.domain_handler`: workflow-log append/list domain
  command handler and passive `audit.events` sink.
- `shared.contracts.task_status`: shared task-status record and store protocol.
- `redis_status_node`: Redis adapter shell and in-memory unit-test store for the
  shared task-status contract. Redis status store composition stays outside the
  task manager package.

## Current Message Path

```text
manager task intake envelope
  -> manager accepted/audit event publication
  -> task manager publishes task request
  -> task service dispatches project plan request
  -> project service publishes project result
  -> task service dispatches helper command
  -> ingestion/retrieval helper publishes helper result
  -> task service publishes task events/results
  -> task manager writes Redis status with TTL

manager/task audit envelopes
  -> workflow log consumes audit.events
  -> workflow log appends durable SQLite entries
```

The implemented path is transport-neutral and uses injected producers/consumers
in tests. Local runtime now starts the broker-first process topology; focused
live Redpanda plus Redis smoke coverage verifies topic bootstrap,
publish/consume, manager intake publication, and Redis status readback.

## Verification

Focused verification currently passes with:

```bash
pytest tests/test_message_contracts.py \
  tests/broker/test_redpanda_adapter.py \
  tests/manager/test_service.py \
  tests/task_manager/test_dispatcher.py \
  tests/task_manager/test_server.py \
  tests/project/test_domain_handler.py \
  tests/ingestion/test_helper_handler.py \
  tests/retrieval/test_helper_handler.py \
  tests/redis/test_task_status_store.py -q
```

## Known Gaps

- Live Redpanda/Redis smoke tests are available behind `RAG_LIVE_INFRA=1`; add
  a managed CI job when Docker-backed local infrastructure is available there.
- Manager-facing workflow query/result flow is still reserved; workflow-log
  audit observation is integrated through `audit.events`.
