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
  domain command dispatch, helper command dispatch, helper-result finalization,
  shared-contract status updates, and final task-result publication.
- `project_service.domain_handler`: project-domain command handler that returns
  project plan/info results without dispatching helper work.
- `ingestion_service.server.domain_handler`: ingestion helper command handler.
- `retrieval_service.server.domain_handler`: retrieval helper command handler.
- `workflow_log_service.domain_handler`: workflow-log append/list domain
  command handler.
- `shared.contracts.task_status`: shared task-status record and store protocol.
- `redis_status_node`: Redis adapter shell and in-memory unit-test store for the
  shared task-status contract. Redis status store composition stays outside the
  task manager package.

## Current Message Path

```text
manager task intake envelope
  -> task manager dispatches domain command
  -> project service publishes project result
  -> task manager dispatches helper command
  -> ingestion/retrieval helper publishes helper result
  -> task manager writes Redis status with TTL and publishes task result
```

The implemented path is transport-neutral and uses injected producers/consumers
in tests. Live Redpanda startup, topic bootstrap, process supervision, and full
local-runner wiring are still pending.

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

- Redpanda adapter is not yet wired into every server runtime.
- Local runner still contains compatibility paths.
- Task manager fan-in is single-helper-result for now.
- Redis adapter shell exists, but live Redis integration tests are pending.
- Project, ingestion, and retrieval handlers are not yet started as real
  Redpanda consumer processes.
- Workflow-log domain handler exists, but manager-facing workflow query/result
  flow is not fully integrated.
- Task manager server context has injectable consumer loops, but production
  process startup and topic assignment are not fully wired yet.
