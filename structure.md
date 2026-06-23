# Project Structure Golden Rule

## Golden Rule

Local development and production must use the same server topology.

`local` means all required servers run on the local machine. It does not mean
embedded services, in-memory message queues, in-memory storage, or file-based
service communication shortcuts.

Production must use the same code paths as local. Only addresses, credentials,
ports, and deployment-specific values should change through `configs/` and env
files.

## Required Runtime Shape

Each major part must be an independent server or node:

- Manager service is one server.
- Task manager service is one server.
- Each project service is one server.
- Each other domain service, such as workflow logging or memory, is one server.
- Each ingestion worker is one server/process.
- Each retrieval/storage node is one server/process.
- The small SQLite database must be treated as a database node, not as hidden
  in-process state.
- A small Redis node must be treated as the task-status store, not as hidden
  in-process state.
- The message broker must be one independent server. Use Redpanda for now.
- Workflow log must run as its own service/consumer when enabled.

## Service Boundary Rule

Each independent server must live in its own independent top-level folder.

Service code must not cross-reference another service's internal modules,
repositories, handlers, runtime objects, or implementation details. A service may
only communicate with another service through explicit external contracts such
as HTTP APIs, broker topics/events, protobuf/OpenAPI schemas, shared message
schemas, or configuration values.

Shared code must be limited to stable cross-service contracts and small generic
utilities. Shared packages must not contain business logic that belongs to a
specific service, and they must not become a hidden runtime coupling layer.

There must be no shared parent classes, base service classes, inherited server
frameworks, or cross-service runtime abstractions between independent servers.
Each server must own its own independent workspace, runtime entrypoint,
dependency wiring, application lifecycle, and service-specific implementation.
Code reuse between servers is allowed only for explicit external contracts,
schema definitions, protocol clients, or truly generic utilities that do not
control server behavior.

The intended structure follows standard microservice design:

- Each service owns its source code, configuration, tests, runtime entrypoint,
  and deployment definition.
- Each service can be built, tested, started, and deployed independently.
- Service-to-service communication goes through the broker or public service
  APIs, never direct imports into another service folder.
- Data ownership is explicit. A service must not directly read or mutate another
  service's private database, storage files, queues, or in-memory state.
- Local development uses the same service boundaries as production.

## Config And Test Layout Rule

Service configuration must be separated by service under `configs/`.

Each independent server or node should have its own config folder, for example
`configs/manager/`, `configs/ingestion/`, `configs/retrieval/`,
`configs/project/`, `configs/storage/`, `configs/sqlite/`, and
`configs/broker/`, and `configs/redis/`. Shared environment defaults may exist only for truly common
deployment values, and service-specific settings must stay in the owning
service's config folder.

Tests must also be separated by service under `tests/`.

Each independent server or node should have its own test folder, for example
`tests/manager/`, `tests/ingestion/`, `tests/retrieval/`, `tests/project/`,
`tests/storage/`, `tests/sqlite/`, `tests/redis/`, and `tests/broker/`. Cross-service tests
should live in an explicit integration or end-to-end folder such as
`tests/integration/`, and they must exercise services through public APIs or the
broker rather than importing service internals across folders.

## Not Allowed As Local Shortcuts

The local runner and local config must not rely on:

- Embedded project service inside manager.
- Embedded ingestion worker inside manager or project service.
- Embedded retrieval API/service inside manager or project service.
- In-memory message queues for service-to-service communication.
- SQLite queues as the primary broker substitute.
- In-memory repositories for runtime state.
- In-memory object storage for runtime data.
- File-based communication between services.
- Special local-only execution paths that production does not use.

Unit tests may use fakes or in-memory objects when testing isolated behavior,
but runtime modes and integration tests must follow the server topology above.

## Broker Rule

Redpanda is the broker target for now.

The broker should provide the communication path between independent services,
including at minimum:

- Manager-authenticated public requests to the task manager intake stream.
- Task-manager-issued commands to the selected domain service.
- Task-manager-issued helper commands to nodes such as ingestion, storage,
  retrieval, or other helpers after domain services return plans/info.
- Helper-node results and events back to the broker.
- Task lifecycle, status, fan-out, and fan-in messages to the task manager.
- Service event publication for workflow logging.

Retries, leases, attempt counts, backoff, and dead-letter queues are explicitly
out of scope for now. Do not add them until requested.

## Local Runner Rule

The local runner must start real local servers/nodes, not embedded shortcuts:

- Redpanda broker.
- Redis task-status node.
- Qdrant or retrieval storage node.
- SQLite database node or configured database service.
- Manager server.
- Task manager server.
- Project service server.
- Workflow logging service server when enabled.
- Ingestion worker server/process.
- Retrieval index worker server/process.
- Retrieval HTTP/search/delete server.

Local and production should differ only by config values such as hostnames,
ports, credentials, and paths.

## Design Implication

The manager is the public API and auth gate. It authenticates and validates the
caller, creates the request envelope, and publishes the request to the broker.
It must not directly route business operations to project, workflow, ingestion,
retrieval, or storage internals.

The broker is the required communication path between independent servers.
Normal runtime flow is:

```text
client
  -> manager/auth server
  -> broker
  -> task manager
  -> broker
  -> domain service, such as project service, workflow logging service, memory service
  -> broker
  -> task manager
  -> broker
  -> helper nodes, such as ingestion, storage, retrieval, or other helpers
  -> broker
  -> task manager
```

Domain services own service-specific information, policy, config, and planning,
but they are triggered by task-manager messages, not by the public manager. For
project-document work, the project service owns project config, scope, and
request planning. It returns domain plans/info through the broker. Workflow
logging owns workflow-log records and queries. Other domain services own their
own service-specific information.

Helper nodes perform concrete work from task-manager-issued broker commands.
Ingestion owns source handling, parsing, preparation, and chunking. Retrieval
owns retrieval/index/search/delete execution and placement. Storage nodes own
durable storage operations. Helper nodes communicate through the broker and must
not be called by direct imports.

The task manager owns task lifecycle, coordination, dispatch, fan-out/fan-in
state, status, and final task result aggregation. It receives manager intake
events, triggers domain task servers through Redpanda, dispatches helper-node
work after domain planning, receives service/helper results through the broker,
and keeps Redis task status updated by `task_id`.

Redis is the fast task-status store. The manager may read Redis directly for
client status checks by `task_id`. Completed task statuses must have a TTL so
old completed task records expire automatically. Redis must not be used as the
message broker; Redpanda remains the broker for service-to-service messages.
