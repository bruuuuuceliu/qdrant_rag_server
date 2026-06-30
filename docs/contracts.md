# Contracts

## Manager Routing

The implemented route contract lives in `manager_service.routing`.

Inputs:

- `operation`: `ingest`, `search`, `delete`, or `status`
- `data_type`: `project_document`, `agent_memory`, or `workflow_log`
- optional project/user/KB identifiers

Manager routing now produces task intake only. The manager does not call
project, workflow, ingestion, retrieval, or storage internals directly. It
publishes an authenticated task-intake envelope to Redpanda and reads task
status from Redis by `task_id`.

## Broker Envelope

Runtime messages use `shared.contracts.MessageEnvelope`.

Required envelope fields:

- `message_id`
- `correlation_id`
- `task_id`
- `producer`
- `message_type`
- `data_type`
- `schema_version`
- `created_at`
- `headers`
- `payload`

Envelope payloads are plain mappings. Services may import shared contracts, but
must not import another service's internals to parse a message.

## Canonical Topics

Canonical topic names live in `shared.contracts.TOPICS`.

| Topic | Producer | Consumer | Purpose |
| --- | --- | --- | --- |
| `task.intake` | manager service | task manager | Accepted public requests after auth/validation. |
| `manager.request.accepted` | manager service | audit/status observers | Manager acceptance events. |
| `audit.events` | manager/task services | workflow/audit observers | Audit trail events. |
| `task.requests` | task manager | task service | Normalized task execution requests. |
| `project.plan.requests` | task service | project service | Project-document planning requests. |
| `project.plan.results` | project service | task service | Project plans and domain results. |
| `helper.ingestion.commands` | task service | ingestion helper | Source loading and chunk preparation. |
| `helper.ingestion.results` | ingestion helper | task service | Ingestion job/chunk preparation results. |
| `helper.retrieval.commands` | task service | retrieval helper | Search/delete/raw-document work. |
| `helper.retrieval.results` | retrieval helper | task service | Retrieval helper results. |
| `helper.retrieval_index.commands` | task service | retrieval index helper | Chunk indexing work. |
| `helper.retrieval_index.results` | retrieval index helper | task service | Indexing results. |
| `helper.storage.commands` | task service | storage helper | Object storage work. |
| `helper.storage.results` | storage helper | task service | Storage helper results. |
| `task.events` | task service | task manager | Running/step/failure lifecycle updates. |
| `task.results` | task service | task manager | Final task result payloads. |
| `task.dead_letters` | task service | operators/observers | Failed non-retryable messages. |

## Task Payloads

Typed task payload DTOs live in `shared.contracts.task_messages`.

- `TaskIntakePayload`: manager-accepted public request.
- `TaskRequestPayload`: normalized task-manager request to task service.
- `ProjectPlanRequestPayload`: task-service request to project planning.
- `ProjectPlanResultPayload`: project planning result.
- `HelperCommandPayload`: task-service command for a helper node.
- `HelperResultPayload`: helper result consumed by task service.
- `TaskEventPayload`: task lifecycle event.
- `TaskExecutionResultPayload`: final task execution result.
- `DeadLetterPayload`: failed message detail for dead-letter publication.

Every payload carries the operation and enough source identifiers to correlate
the next message with the original `task_id`, `correlation_id`, and source
message.

## Status Contract

Task status is stored through `shared.contracts.TaskStatusStore` and represented
by `TaskStatusRecord`.

The task manager writes Redis task status records after consuming task
events/results. The manager reads Redis by `task_id` for status checks. Completed
task statuses expire by configured TTL.

Current accepted status values include:

- `accepted`
- `queued`
- `running`
- `dispatched`
- `completed`
- `failed`

Client-side examples must treat non-terminal accepted/running values as valid
in-flight states.

## Project Planning

Project planning can attach an optional `placement_plan` mapping to ingest,
search, delete, and index work. The plan identifies routing keys, placement
version, and target shard IDs.

Current local behavior:

- project planning emits `placement_plan` when placement is enabled
- retrieval search/delete and retrieval-index command contracts preserve it
- retrieval indexing resolves placement targets to Qdrant stores and writes the
  primary plus configured replica targets
- retrieval search groups targets by routing key, searches one target per
  group, falls back from primary to replicas, and merges bucket hits by score
- retrieval delete resolves the same placement write set and removes dense and
  sparse records from each target
- search cache keys are namespaced by placement version, shard ID, and routing
  key

## Ingestion Helper

The ingestion helper is triggered by `helper.ingestion.commands`.

It owns:

- ingestion job records
- source loading
- parsing, cleaning, and chunking
- neutral chunk preparation
- ingestion helper result publication

Ingestion settings are loaded from `configs.ingestion`:

- `INGESTION_SERVICE_ENABLED`
- `INGESTION_SERVICE_NAME`
- `INGESTION_HELPER_COMMAND_TOPIC`
- `INGESTION_WORKER_COUNT`
- `INGESTION_QUEUE_MAXSIZE`
- `INGESTION_JOB_DB_PATH`

`IngestRequest` still supports `raw_text` and `raw_content` metadata because the
compatibility gRPC proto exposes string metadata only.

## Retrieval Helper

Retrieval command contracts live under `retrieval_service.retrieval.contracts`
and are consumed by the retrieval helper behind `helper.retrieval.commands`.

Current operations:

- search project-document chunks
- delete a document from retrieval stores and caches
- read raw document bytes from object storage

Retrieval responses use plain response-envelope mappings with request ID, result
payload, retryable flag, and error text. Raw bytes are serialized through
transport-safe metadata rather than leaking Python `bytes` objects.

## Retrieval Index Helper

Retrieval indexing command parsing lives in
`retrieval_service.indexing.commands`. The helper is triggered by
`helper.retrieval_index.commands`.

Index commands carry:

- `request_id`
- `job_id`
- `collection_name`
- `chunks`
- `payloads`
- `retrieval_config`
- optional `placement_plan`

Prepared chunks remain neutral. Collection policy, retrieval configuration, and
placement assignment are project/task-service responsibilities, not indexing
helper responsibilities.

## Compatibility Boundary

The public compatibility gRPC `RagService` remains at the manager edge. It is a
transport adapter into the broker-first flow:

- `Ingest` returns a task ID with `accepted`
- `GetIngestJobStatus` reads task status
- `Search` publishes a task and waits for the task result within the gRPC
  deadline
- `Generate` is not part of the broker-first manager flow and returns
  `UNIMPLEMENTED`

New internal service work should use canonical service packages and shared
broker contracts, not compatibility shims or deleted local queue transports.
