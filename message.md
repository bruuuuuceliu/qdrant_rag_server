# Service Message Design

Status: current broker-first contract.

Runtime service-to-service communication uses Redpanda-compatible topics and
`shared.contracts.MessageEnvelope`. Payload DTOs live in
`shared.contracts.task_messages`.

## Rules

- Manager authenticates public requests and publishes task-intake envelopes.
- Every runtime message carries `task_id`, `correlation_id`, `message_id`,
  `message_type`, `data_type`, `schema_version`, and a plain mapping payload.
- Services consume only shared contracts and their own implementation modules.
- Task status is written to Redis by task manager and read by manager by
  `task_id`.
- Customer context and placement hints are explicit payload sections.
- Workflow log messages are observational and must not block business success.

## Envelope

```json
{
  "message_id": "msg-1",
  "correlation_id": "corr-1",
  "task_id": "task-1",
  "producer": "manager_service",
  "message_type": "request.accepted",
  "data_type": "project_document",
  "schema_version": "1",
  "created_at": "2026-06-29T00:00:00+00:00",
  "headers": {},
  "payload": {
    "operation": "ingest",
    "request": {},
    "context": {}
  }
}
```

## Main Flow

```text
client
  -> manager_service
  -> task.intake
  -> task_manager_service
  -> task.requests
  -> task_service
  -> project.plan.requests
  -> project_service
  -> project.plan.results
  -> task_service
  -> helper.*.commands
  -> helper services
  -> helper.*.results
  -> task_service
  -> task.events / task.results
  -> task_manager_service
  -> Redis task status
```

## Task Intake Payload

```json
{
  "operation": "search",
  "request": {
    "project_id": "p1",
    "user_id": "u1",
    "query": "deployment notes",
    "metadata": {"data_type": "project_document"}
  },
  "context": {
    "request_id": "corr-1",
    "auth_context": {},
    "customer_context": {},
    "placement_hint": {}
  }
}
```

## Helper Command Payload

```json
{
  "operation": "ingest",
  "helper": "ingestion",
  "plan": {
    "project_id": "p1",
    "user_id": "u1",
    "kb_id": "kb",
    "doc_id": "doc-1",
    "placement_plan": {}
  },
  "source_message_id": "msg-1"
}
```

## Helper Result Payload

```json
{
  "operation": "ingest",
  "helper": "ingestion",
  "result": {
    "ok": true,
    "job_id": "task-1"
  },
  "attempt": 1,
  "retryable": false,
  "error": "",
  "source_message_id": "msg-2"
}
```

## Placement

Project planning may attach `placement_plan` to ingest, search, delete, and
index work. Retrieval indexing/search/delete preserve that plan and resolve it
to Qdrant targets inside retrieval-owned code.
