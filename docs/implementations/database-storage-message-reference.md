# Database, Storage, And Message Reference

This document is the implementation reference for the current broker-first
message sending, database, and storage phase. It records the code-owned
structures that should stay stable unless the owning service changes its
contract.

## Message Topology

Canonical topic names live in `shared.contracts.TOPICS`.

| Topic | Producer | Consumer | Payload contract |
| --- | --- | --- | --- |
| `task.intake` | `manager_service` | `task_manager_service` | `TaskIntakePayload` / `TaskRequestPayload` |
| `manager.request.accepted` | `manager_service` | observers | plain accepted-event mapping |
| `audit.events` | `manager_service`, task/domain services | `workflow_log_service` | `MessageType.AUDIT_EVENT` payload mapping |
| `task.requests` | `task_manager_service` | `task_service` | `TaskRequestPayload` |
| `project.plan.requests` | `task_service` | `project_service` | `ProjectPlanRequestPayload` |
| `project.plan.results` | `project_service` | `task_service` | `ProjectPlanResultPayload` |
| `helper.ingestion.commands` | `task_service` | `ingestion_service` | `HelperCommandPayload` |
| `helper.ingestion.results` | `ingestion_service` | `task_service` | `HelperResultPayload` |
| `helper.storage.commands` | `task_service` | `storage_node` | `HelperCommandPayload` |
| `helper.storage.results` | `storage_node` | `task_service` | `HelperResultPayload` |
| `helper.retrieval.commands` | `task_service` | `retrieval_service` | `HelperCommandPayload` |
| `helper.retrieval.results` | `retrieval_service` | `task_service` | `HelperResultPayload` |
| `helper.retrieval_index.commands` | `task_service` | `retrieval_service.indexing` | `HelperCommandPayload` |
| `helper.retrieval_index.results` | `retrieval_service.indexing` | `task_service` | `HelperResultPayload` |
| `task.events` | `task_service` | `task_manager_service` | `TaskEventPayload` |
| `task.results` | `task_service` | `task_manager_service` | `TaskExecutionResultPayload` |
| `task.dead_letters` | `task_service` | operators/observers | `DeadLetterPayload` |
| `domain.workflow_log.commands` | task/domain callers | `workflow_log_service` | `DomainCommandPayload` |
| `domain.workflow_log.results` | `workflow_log_service` | task/domain callers | `DomainResultPayload` |

All runtime envelopes use `shared.contracts.MessageEnvelope` with schema version
`1`, string IDs, string `message_type`, string `data_type`, string headers, and
a mapping payload.

Broker delivery rule: the Redpanda adapter disables consumer auto-commit.
Service contexts commit offsets only after successful handler/dispatcher
completion. Failed handlers leave offsets uncommitted for at-least-once
redelivery.

## Public Data Types

Shared route labels live in `shared.contracts.data_types`.

| Data type | Owner | Current public status |
| --- | --- | --- |
| `project_document` | `project_service` planning plus helper services | executable |
| `agent_memory` | `memory_service` | reserved |
| `workflow_log` | `workflow_log_service` | reserved at manager route edge; command API exists internally |

## Status Store

Redis task status is not a broker substitute. It is the client-facing read
model for `task_id`.

| Key/config | Meaning |
| --- | --- |
| `REDIS_TASK_STATUS_URL` | Redis URL used by manager and task manager |
| `REDIS_TASK_STATUS_KEY_PREFIX` | Prefix for task status keys |
| `REDIS_TASK_COMPLETED_TTL_SECONDS` | TTL for completed/failed terminal records |

Record schema: `TaskStatusRecord` in `shared.contracts.task_status`.

| Field | Type | Notes |
| --- | --- | --- |
| `task_id` | text | required key |
| `status` | text | `accepted`, `queued`, `running`, `dispatched`, `completed`, `failed`, `rejected` |
| `correlation_id` | text | request correlation |
| `data_type` | text | route label |
| `operation` | text | `ingest`, `search`, `delete`, etc. |
| `result` | object | final or latest status payload |
| `error` | text | failure summary |

## SQLite Node Control Plane

The SQLite node owns database allocation metadata under
`SQLITE_NODE_DATABASE_ROOT`. It does not inspect service-private business
tables.

Metadata database: `_sqlite_node.db`.

| Table | Purpose |
| --- | --- |
| `db_node_databases` | logical database ownership, purpose, path, version, state |
| `db_node_schema_versions` | service-reported schema version/checksum |
| `db_node_allocations` | allocation history for requested database paths |
| `db_node_health_checks` | persisted readiness checks for allocated databases |

Table: `db_node_databases`.

| Column | Type | Notes |
| --- | --- | --- |
| `database_name` | `TEXT PRIMARY KEY` | logical service database name |
| `owner_service` | `TEXT NOT NULL` | owning service or node |
| `purpose` | `TEXT NOT NULL` | human-readable purpose |
| `relative_path` | `TEXT NOT NULL UNIQUE` | file path under `SQLITE_NODE_DATABASE_ROOT` |
| `schema_version` | `INTEGER NOT NULL` | owner-reported current schema version |
| `state` | `TEXT NOT NULL` | allocation state such as `active` |
| `created_at` | `TEXT NOT NULL` | SQLite timestamp |
| `updated_at` | `TEXT NOT NULL` | SQLite timestamp |

Indexes: `idx_db_node_databases_owner`, `idx_db_node_databases_state`.

Table: `db_node_schema_versions`.

| Column | Type | Notes |
| --- | --- | --- |
| `owner_service` | `TEXT NOT NULL` | owner namespace |
| `database_name` | `TEXT NOT NULL` | logical database name |
| `schema_name` | `TEXT NOT NULL` | schema or migration stream |
| `version` | `INTEGER NOT NULL` | owner-reported schema version |
| `checksum` | `TEXT NOT NULL` | optional migration checksum |
| `applied_at` | `TEXT NOT NULL` | SQLite timestamp |

Primary key: `(owner_service, database_name, schema_name)`.

Table: `db_node_allocations`.

| Column | Type | Notes |
| --- | --- | --- |
| `allocation_id` | `TEXT PRIMARY KEY` | allocation event ID |
| `database_name` | `TEXT NOT NULL` | logical database name |
| `owner_service` | `TEXT NOT NULL` | owning service |
| `requested_name` | `TEXT NOT NULL` | raw requested database name |
| `resolved_path` | `TEXT NOT NULL` | absolute file path returned to caller |
| `created_at` | `TEXT NOT NULL` | SQLite timestamp |

Indexes: `idx_db_node_allocations_database`, `idx_db_node_allocations_owner`.

Table: `db_node_health_checks`.

| Column | Type | Notes |
| --- | --- | --- |
| `check_id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | health event ID |
| `database_name` | `TEXT NOT NULL` | logical database name |
| `owner_service` | `TEXT NOT NULL` | owning service |
| `ok` | `INTEGER NOT NULL` | readiness result |
| `error` | `TEXT NOT NULL` | failure detail |
| `checked_at` | `TEXT NOT NULL` | SQLite timestamp |

Index: `idx_db_node_health_database_time`.

Local runner allocations:

| Owner | Logical database | Env var |
| --- | --- | --- |
| `project_service` | `project_config` | `PROJECT_CONFIG_DB_PATH` |
| `retrieval_service` | `response_cache` | `RAG_RESPONSE_CACHE_DB_PATH` |
| `ingestion_service` | `ingestion_jobs` | `INGESTION_JOB_DB_PATH` |
| `workflow_log_service` | `workflow_log` | `WORKFLOW_LOG_DB_PATH` |
| `retrieval_service` | `retrieval_placement` | `RETRIEVAL_PLACEMENT_DB_PATH` |
| `task_service` | `task_service_state` | `TASK_SERVICE_STATE_DB_PATH` |

## Service-Owned Tables

### Project Config

Owner: `project_service.config.SQLiteProjectConfigRepository`.

Database path: `PROJECT_CONFIG_DB_PATH`.

Table: `projects`.

| Column | Type | Notes |
| --- | --- | --- |
| `project_id` | `TEXT PRIMARY KEY` | logical project |
| `project_type` | `TEXT NOT NULL` | adapter key |
| `active_embedding_version` | `TEXT NOT NULL` | current embedding version |
| `embedding_model` | `TEXT NOT NULL` | configured embedding model |
| `reranker_model` | `TEXT NOT NULL` | configured reranker |
| `chunker_config_json` | `TEXT NOT NULL` | JSON object |
| `retrieval_config_json` | `TEXT NOT NULL` | JSON object |
| `cache_config_json` | `TEXT NOT NULL` | JSON object |
| `created_at` | `TEXT NOT NULL` | SQLite timestamp |
| `updated_at` | `TEXT NOT NULL` | SQLite timestamp |

Index: `idx_projects_project_type(project_type)`.

### Task Service State

Owner: `task_service.repository.SQLiteTaskStateRepository`.

Database path: `TASK_SERVICE_STATE_DB_PATH`.

Important config keys:

| Key | Meaning |
| --- | --- |
| `TASK_SERVICE_NAME` | broker consumer group base name |
| `TASK_SERVICE_TASK_REQUEST_TOPIC` | normalized task request topic |
| `TASK_SERVICE_PROJECT_PLAN_REQUEST_TOPIC` | project planning request topic |
| `TASK_SERVICE_PROJECT_PLAN_RESULT_TOPIC` | project planning result topic |
| `TASK_SERVICE_TASK_EVENT_TOPIC` | lifecycle event topic |
| `TASK_SERVICE_TASK_RESULT_TOPIC` | final task result topic |
| `TASK_SERVICE_DEAD_LETTER_TOPIC` | terminal helper failure topic |
| `TASK_SERVICE_STATE_DB_PATH` | SQLite execution state database path |
| `TASK_SERVICE_MAX_ATTEMPTS` | max helper result attempts before terminal failure |
| `TASK_SERVICE_HELPER_LEASE_SECONDS` | helper command lease duration before expired-lease recovery |
| `TASK_SERVICE_RETRY_BACKOFF_SECONDS` | delayed retry schedule; `0` preserves immediate retry dispatch |
| `TASK_SERVICE_RECOVERY_ENABLED` | enables DB-backed due retry and expired lease recovery |
| `TASK_SERVICE_RECOVERY_POLL_SECONDS` | recovery loop polling interval |
| `TASK_SERVICE_RECOVERY_BATCH_SIZE` | max helper steps claimed per recovery pass |

Tables: `task_executions`, `task_steps`, `task_step_attempts`, and
`task_results`.

Table: `task_executions`.

| Column | Type | Notes |
| --- | --- | --- |
| `task_id` | `TEXT PRIMARY KEY` | task execution key |
| `data_type` | `TEXT NOT NULL` | envelope data type used to recreate helper commands during recovery |
| `correlation_id` | `TEXT NOT NULL` | envelope correlation ID used during recovery |
| `operation` | `TEXT NOT NULL` | latest task operation used as a recovery fallback |
| `created_at` | `TEXT NOT NULL` | SQLite timestamp |
| `updated_at` | `TEXT NOT NULL` | SQLite timestamp |

Table: `task_steps`.

| Column | Type | Notes |
| --- | --- | --- |
| `task_id` | `TEXT NOT NULL` | foreign key to `task_executions` |
| `helper` | `TEXT NOT NULL` | helper topic |
| `expected` | `INTEGER NOT NULL` | expected fan-in flag |
| `completed` | `INTEGER NOT NULL` | successful result flag |
| `failed` | `INTEGER NOT NULL` | failed result flag |
| `operation` | `TEXT NOT NULL` | operation for retry command rebuild |
| `plan_json` | `TEXT NOT NULL` | helper command plan JSON |
| `result_json` | `TEXT NOT NULL` | helper result JSON |
| `attempt` | `INTEGER NOT NULL` | latest helper attempt number |
| `last_status` | `TEXT NOT NULL` | latest step status such as `dispatched`, `retrying`, `completed`, or `failed` |
| `retryable` | `INTEGER NOT NULL` | latest result retryable flag |
| `next_attempt_at` | `TEXT` | scheduled retry timestamp; null for immediate/unscheduled work |
| `lease_owner` | `TEXT NOT NULL` | current dispatch/recovery claim owner |
| `lease_expires_at` | `TEXT` | claim deadline timestamp |
| `last_dispatched_at` | `TEXT` | last helper command dispatch timestamp |
| `last_result_at` | `TEXT` | last helper result timestamp |
| `last_error` | `TEXT NOT NULL` | latest helper error text |
| `last_source_message_id` | `TEXT NOT NULL` | latest helper command/result source message ID |
| `created_at` | `TEXT NOT NULL` | SQLite timestamp |
| `updated_at` | `TEXT NOT NULL` | SQLite timestamp |

Primary key: `(task_id, helper)`.
Indexes: `idx_task_steps_task_complete`, `idx_task_steps_helper`,
`idx_task_steps_next_attempt`, and `idx_task_steps_lease`.

Table: `task_step_attempts`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ordered attempt event ID |
| `task_id` | `TEXT NOT NULL` | foreign key to `task_steps` |
| `helper` | `TEXT NOT NULL` | helper topic |
| `attempt` | `INTEGER NOT NULL` | helper attempt number |
| `event` | `TEXT NOT NULL` | `dispatch` or `result` |
| `status` | `TEXT NOT NULL` | `dispatched`, `retrying`, `completed`, or `failed` |
| `retryable` | `INTEGER NOT NULL` | retryable flag from result processing |
| `source_message_id` | `TEXT NOT NULL` | command/result source message ID |
| `failed_message_id` | `TEXT NOT NULL` | failed result message ID when retry/dead-letter applies |
| `result_json` | `TEXT NOT NULL` | result/failure payload JSON |
| `error` | `TEXT NOT NULL` | error text |
| `next_attempt_at` | `TEXT` | scheduled retry timestamp |
| `lease_owner` | `TEXT NOT NULL` | claim owner recorded at dispatch |
| `lease_expires_at` | `TEXT` | claim deadline timestamp |
| `created_at` | `TEXT NOT NULL` | SQLite timestamp |

Indexes: `idx_task_step_attempts_task_helper`,
`idx_task_step_attempts_status`.

Table: `task_results`.

| Column | Type | Notes |
| --- | --- | --- |
| `task_id` | `TEXT PRIMARY KEY` | foreign key to `task_executions` |
| `final_status` | `TEXT NOT NULL` | terminal status after publication |
| `result_json` | `TEXT NOT NULL` | final result JSON object |
| `published` | `INTEGER NOT NULL` | idempotency flag |
| `published_at` | `TEXT` | SQLite timestamp when `published = 1`; otherwise null |
| `updated_at` | `TEXT NOT NULL` | SQLite timestamp |

Legacy local databases with the old `task_states` table are migrated into the
explicit tables when `SQLiteTaskStateRepository` starts. The legacy table is not
used for new writes.

### Ingestion Jobs

Owner: `ingestion_service.jobs.SQLiteIngestionJobRepository`.

Database path: `INGESTION_JOB_DB_PATH`.

Table: `ingestion_jobs`.

| Column | Type | Notes |
| --- | --- | --- |
| `job_id` | `TEXT PRIMARY KEY` | ingestion-owned job ID |
| `project_id` | `TEXT NOT NULL` | project scope |
| `user_id` | `TEXT NOT NULL` | user scope |
| `kb_id` | `TEXT NOT NULL` | knowledge-base scope |
| `doc_id` | `TEXT NOT NULL` | document ID |
| `source_uri` | `TEXT NOT NULL` | source descriptor |
| `data_type` | `TEXT NOT NULL` | default `project_document` |
| `status` | `TEXT NOT NULL` | job status |
| `error` | `TEXT` | failure detail |
| `content_hash` | `TEXT` | prepared content hash |
| `metadata_json` | `TEXT NOT NULL` | ingestion metadata JSON |
| `created_at` | `REAL NOT NULL` | epoch seconds |
| `updated_at` | `REAL NOT NULL` | epoch seconds |

Indexes: `idx_ingestion_jobs_project_user`, `idx_ingestion_jobs_doc`,
`idx_ingestion_jobs_status`.

### Workflow Log

Owner: `workflow_log_service.repository.SQLiteWorkflowLogRepository`.

Database path: `WORKFLOW_LOG_DB_PATH`.

Table: `workflow_log_entries`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | ordered log ID |
| `event` | `TEXT NOT NULL` | event name |
| `job_id` | `TEXT NOT NULL` | task/job ID |
| `status` | `TEXT NOT NULL` | event status |
| `project_id` | `TEXT NOT NULL` | project scope |
| `user_id` | `TEXT NOT NULL` | user scope |
| `kb_id` | `TEXT` | optional KB |
| `doc_id` | `TEXT` | optional document |
| `data_type` | `TEXT` | route label |
| `content_hash` | `TEXT` | optional content hash |
| `raw_storage_key` | `TEXT` | optional raw storage key |
| `error` | `TEXT` | optional error |
| `topic` | `TEXT NOT NULL` | source topic such as `audit.events` |
| `message_key` | `TEXT NOT NULL` | broker key |
| `headers_json` | `TEXT NOT NULL` | JSON headers |
| `payload_json` | `TEXT NOT NULL` | full event payload JSON |
| `created_at` | `REAL NOT NULL` | epoch seconds |

Indexes: `idx_workflow_log_job`, `idx_workflow_log_project_user`,
`idx_workflow_log_event`.

The workflow-log worker consumes both `WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC` and
`WORKFLOW_LOG_AUDIT_TOPIC`. Audit events are appended without publishing
domain results. Domain append/list commands still publish
`domain.workflow_log.results`.

### Retrieval Response Cache

Owner: `retrieval_service.services.cache.Tier2ResponseCache`.

Database path: `RAG_RESPONSE_CACHE_DB_PATH`.

Table: `responses`.

| Column | Type | Notes |
| --- | --- | --- |
| `project_id` | `TEXT NOT NULL` | cache scope |
| `user_id` | `TEXT NOT NULL` | cache scope |
| `cache_key` | `TEXT NOT NULL` | query/cache identity |
| `response` | `TEXT NOT NULL` | cached response |
| `expires_at` | `REAL NOT NULL` | epoch expiration |

Primary key: `(project_id, user_id, cache_key)`.
Index: `idx_responses_expires(expires_at)`.

### Retrieval Placement

Owner: `retrieval_service.placement.SQLitePlacementRegistry`.

Database path: `RETRIEVAL_PLACEMENT_DB_PATH`.

Tables:

| Table | Purpose |
| --- | --- |
| `retrieval_shards` | shard endpoints, weights, states, and load hints |
| `retrieval_placements` | routing key to primary/replica shard placement |
| `retrieval_routing_policies` | project routing mode, bucket count, replica count, read fanout |

Important config keys:

- `RETRIEVAL_PLACEMENT_ENABLED`
- `RETRIEVAL_PLACEMENT_DB_PATH`
- `RETRIEVAL_PLACEMENT_ROUTING_MODE`
- `RETRIEVAL_PLACEMENT_BUCKET_COUNT`
- `RETRIEVAL_PLACEMENT_REPLICATION_FACTOR`
- `RETRIEVAL_PLACEMENT_SHARD_ID`
- `RETRIEVAL_PLACEMENT_CLUSTER_ID`

## Raw Storage

There are two current storage surfaces:

1. `storage_node`: broker helper for task-service raw put/get/delete.
2. `retrieval_service.storage`: retrieval-owned object storage abstraction for
   raw-document backup reads/deletes.

### Storage Node

Config:

| Key | Meaning |
| --- | --- |
| `STORAGE_NODE_SERVICE_NAME` | broker consumer group/service name |
| `STORAGE_NODE_COMMAND_TOPIC` | command topic, default `helper.storage.commands` |
| `STORAGE_NODE_RESULT_TOPIC` | result topic, default `helper.storage.results` |
| `STORAGE_NODE_ROOT` | filesystem root for stored objects |

Command plan fields:

| Operation | Required fields | Result |
| --- | --- | --- |
| `put` | `key`, `value` | `{ok, key}` |
| `get` | `key` | `{ok, key, value}` or `{ok: false, error: not_found}` |
| `delete` | `key` | `{ok, key}` |

Keys must be relative paths. Absolute paths and `..` segments are rejected.

### Retrieval Object Storage

Config:

| Key | Meaning |
| --- | --- |
| `RAG_OBJECT_STORAGE_PROVIDER` | `filesystem`, `memory`, or S3-compatible provider |
| `RAG_OBJECT_STORAGE_BASE_PATH` | filesystem provider root |
| `RAG_OBJECT_STORAGE_PATH` | config helper filesystem path |
| `RAG_S3_ENDPOINT_URL` | S3-compatible endpoint |
| `RAG_S3_BUCKET` | S3 bucket |
| `RAG_S3_REGION` | S3 signing region |

Storage keys are built from project/user/document identifiers. External HTTP
or S3-compatible calls are backend access, not service-to-service runtime
transport.

## Local Runtime Defaults

`examples/local/run-all.sh` sets local database and storage paths under
`RAG_LOCAL_DATA_DIR`, then asks the SQLite node to allocate service-owned
database files. Local and production should differ by addresses, credentials,
paths, and deployment settings, not by embedded runtime shortcuts.
Smoke runs that do not explicitly set `RAG_EXAMPLE_EMBEDDING_VERSION` derive
the project embedding version from `RAG_EMBEDDING_PROVIDER` and
`RAG_EMBEDDING_DIMENSION`. This keeps Qdrant collection schemas separate when a
developer switches between local model dimensions. The deterministic embedding
provider is available for smoke/offline checks that should not depend on
Hugging Face or remote embedding APIs.

The task-service recovery loop claims rows from `task_steps` when
`next_attempt_at` is due or `lease_expires_at` has passed. Scheduled retries and
expired leases are redispatched with incremented `attempt` while attempts remain
below `TASK_SERVICE_MAX_ATTEMPTS`. Expired leases at the max attempt count are
converted into terminal helper failures and normal dead-letter/final-result
publication. Helper result redelivery is deduplicated by the helper result
envelope `message_id` stored as `failed_message_id` in `task_step_attempts`:
non-terminal duplicate results are acknowledged without creating another
attempt row or helper command, while already-recorded complete fan-in can still
republish the final task result if a previous publish failed before
`task_results.published` was set.

## Remaining Hardening

- Add transactional outbox/inbox support if the runtime needs exactly-once-style
  publish/DB atomicity beyond current at-least-once broker consumption.
- Run the manual GitHub Actions Docker smoke job after runner, broker, Qdrant,
  embedding, or message-topology changes so full Redpanda/Redis/Qdrant smoke
  verification is recorded outside developer machines.
- Add optional uncached sentence-transformers startup evidence for the `local`
  embedding provider.
- Add migration/reindex orchestration for placement changes.
- Keep workflow-log audit observation passive; command/query flows should stay
  separate from the main task success path.
