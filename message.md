# Service Message Design

Status: current local migration contract. Message shapes are transport-neutral
JSON-like payloads carried by local queues, HTTP, gRPC adapters, or direct local
clients.

Current implementation note: optional `placement_plan` payloads are now produced
by local project planning and preserved by retrieval index, search, and delete
command contracts. Split ingestion forwards `placement_plan` metadata to
retrieval indexing. The placement resolver and registries exist under
`retrieval_service.placement`. Runtime execution still needs to route Qdrant
calls to the target shard and fan out bucketed searches.

Multi-database/Qdrant operation is design-only for now. Local messages carry
placement metadata, but services execute against the configured single Qdrant
endpoint.

## Rules

- Every async message has `request_id` and usually `response_topic`.
- Queue messages use the common wrapper `QueueMessage`.
- Service responses use `{request_id, ok, result|error}` envelopes.
- Long-running writes use queues and status polling.
- Manager authenticates public requests, then forwards enriched context to
  project-service task APIs.
- Customer context and database placement marks are explicit, typed payload
  sections. They are not hidden in unstructured metadata.
- Database placement uses project, user, topic, document, and bucket identity.
  KB/session routing is not part of the target placement design.
- Workflow log messages are observational and must not block business success.

## Common Queue Wrapper

Structure:

```json
{
  "topic": "string",
  "key": "string",
  "payload": {},
  "headers": {
    "correlation_id": "string"
  }
}
```

Description: broker-level wrapper used by `shared.queue.QueueBroker`.

Example:

```json
{
  "topic": "ingestion.requests",
  "key": "req-123",
  "payload": {"request_id": "req-123", "request": {}},
  "headers": {"correlation_id": "req-123"}
}
```

## Client To Manager

Method: RPC.

Structure:

```json
{
  "operation": "ingest | search | delete | status",
  "data_type": "project_document",
  "project_id": "string",
  "user_id": "string",
  "topic_id": "string",
  "payload": {}
}
```

Description: public request envelope. Manager authenticates this request,
resolves customer/routing context from auth, and routes project-document work to
project service.

Example:

```json
{
  "operation": "search",
  "data_type": "project_document",
  "project_id": "p1",
  "user_id": "u1",
  "topic_id": "rentals",
  "payload": {"query": "deployment notes"}
}
```

## Manager Auth Context

Method: manager-internal auth result, forwarded to project service.

Structure:

```json
{
  "auth_context": {
    "subject_id": "string",
    "customer_id": "string",
    "tenant_id": "string",
    "roles": ["string"],
    "scopes": ["string"],
    "allowed_project_ids": ["string"],
    "expires_at": 1710000000
  },
  "customer_context": {
    "customer_tier": "standard | premium | internal",
    "region": "string",
    "rate_limit_group": "string"
  },
  "placement_hint": {
    "routing_policy_id": "optional",
    "placement_version": 4,
    "routing_key_hint": "project:p1:topic:rentals"
  }
}
```

Description: auth-derived context. Manager may forward this data, but project
service and retrieval placement still own task policy and database assignment.

Example:

```json
{
  "auth_context": {
    "subject_id": "user-42",
    "customer_id": "cust-9",
    "tenant_id": "tenant-a",
    "roles": ["member"],
    "scopes": ["project:read", "project:write"],
    "allowed_project_ids": ["p1"],
    "expires_at": 1710000000
  },
  "customer_context": {
    "customer_tier": "premium",
    "region": "us-east",
    "rate_limit_group": "premium-east"
  },
  "placement_hint": {
    "placement_version": 4,
    "routing_key_hint": "project:p1:topic:rentals"
  }
}
```

## Manager To Project Service

Method: RPC/local client today; future project-task transport.

Structure:

```json
{
  "request_id": "string",
  "operation": "start_document_ingest_task | search_documents | delete_document | get_document_task_status",
  "auth_context": {},
  "customer_context": {},
  "placement_hint": {},
  "request": {}
}
```

Description: manager-facing project-document task API. Project service retrieves
task-related project/user/topic information, applies policy, resolves database
placement, and orchestrates work.

Example:

```json
{
  "request_id": "req-123",
  "operation": "start_document_ingest_task",
  "auth_context": {"subject_id": "user-42", "customer_id": "cust-9"},
  "customer_context": {"customer_tier": "premium"},
  "placement_hint": {"routing_key_hint": "project:p1:topic:rentals"},
  "request": {
    "project_id": "p1",
    "user_id": "u1",
    "topic_id": "rentals",
    "doc_id": "d1",
    "source_uri": "memory://d1",
    "content_type": "text/plain",
    "raw_text": "hello"
  }
}
```

## Project Planning Output

Method: in-process project service boundary.

Search structure:

```json
{
  "project_id": "string",
  "user_id": "string",
  "topic_id": "string",
  "query_text": "string",
  "collection_name": "string",
  "retrieval_config": {},
  "retrieval_filter": {},
  "placement_plan": {}
}
```

Ingest structure:

```json
{
  "project_id": "string",
  "user_id": "string",
  "topic_id": "string",
  "doc_id": "string",
  "collection_name": "string",
  "retrieval_config": {},
  "chunker_config": {},
  "placement_plan": {}
}
```

Description: project-owned policy result used to call ingestion and retrieval
capabilities without exposing project internals.

Example:

```json
{
  "project_id": "p1",
  "user_id": "u1",
  "topic_id": "rentals",
  "query_text": "deployment notes",
  "collection_name": "rag_p1_v1",
  "retrieval_config": {"top_k": 5},
  "retrieval_filter": {
    "project_id": "p1",
    "allowed_user_ids": ["u1", "shared"],
    "topic_ids": ["rentals"]
  },
  "placement_plan": {
    "placement_version": 4,
    "fanout": false,
    "targets": [
      {
        "routing_key": "project:p1:topic:rentals",
        "shard_id": "retrieval-03",
        "collection_name": "rag_p1_v1"
      }
    ]
  }
}
```

## Database Placement Metadata

Method: project/retrieval planning output attached to ingest, index, search,
and delete work.

Structure:

```json
{
  "placement_plan": {
    "placement_version": 4,
    "fanout": false,
    "targets": [
      {
        "routing_key": "project:p1:topic:rentals:bucket:17",
        "shard_id": "retrieval-03",
        "collection_name": "rag_p1_v1",
        "role": "primary"
      }
    ]
  }
}
```

Description: database assignment information. It keeps retrieval/cache traffic
sticky to the responsible shard. The manager may forward hints, but placement
records are owned by retrieval/database placement.

Assignment rule: new routing keys are assigned with weighted rendezvous
hashing. The chosen shard is stored in a placement record and reused for normal
requests. Do not recompute the target from live load on every request.

Example:

```json
{
  "placement_plan": {
    "placement_version": 7,
    "fanout": true,
    "targets": [
      {"routing_key": "project:p1:topic:rentals:bucket:0", "shard_id": "retrieval-01", "collection_name": "rag_p1_v1"},
      {"routing_key": "project:p1:topic:rentals:bucket:1", "shard_id": "retrieval-02", "collection_name": "rag_p1_v1"}
    ]
  }
}
```

## Placement Assignment Message

Method: project service or retrieval router to placement resolver.

Structure:

```json
{
  "request_id": "string",
  "routing_key": "project:p1:topic:rentals:bucket:17",
  "routing_policy": {
    "routing_mode": "topic_bucketed",
    "bucket_count": 64,
    "replication_factor": 1
  },
  "candidate_shards": [
    {
      "shard_id": "retrieval-01",
      "weight": 100,
      "state": "active",
      "qps": 40,
      "queue_depth": 8,
      "cpu": 0.56,
      "memory": 0.62
    }
  ]
}
```

Description: assignment input for a new routing key. Existing routing keys
should read their stored placement record instead.

Assignment output:

```json
{
  "request_id": "place-1",
  "ok": true,
  "result": {
    "placement_record": {
      "placement_id": "plc-123",
      "placement_version": 4,
      "routing_key": "project:p1:topic:rentals:bucket:17",
      "primary_shard_id": "retrieval-03",
      "replica_shard_ids": [],
      "collection_name": "rag_p1_v1",
      "state": "active"
    },
    "algorithm": "weighted_rendezvous"
  }
}
```

Scoring:

```text
score = stable_hash(routing_key + shard_id) * effective_weight
effective_weight = shard.weight / load_penalty
```

Replica rule: sort shards by rendezvous score; primary is rank 1, replicas are
the next N active shards. Reads prefer primary for cache locality and fail over
to replicas only when needed.

Rebalance rule: create a new placement version. Route new writes to the new
version, reindex/migrate old data, then mark old placements stale. Cache keys
must include `placement_version`.

## Project Or Manager To Ingestion Queue

Topic: `ingestion.requests`.

Method: queue.

Structure:

```json
{
  "request_id": "string",
  "response_topic": "ingestion.requests.responses.<request_id>",
  "request": {
    "project_id": "string",
    "user_id": "string",
    "topic_id": "string",
    "doc_id": "string",
    "source_uri": "string",
    "content_type": "string",
    "raw_text": "string",
    "raw_content": "optional",
    "metadata": {
      "data_type": "project_document",
      "topic_id": "string",
      "collection_name": "string",
      "retrieval_config": {},
      "placement_plan": {}
    }
  }
}
```

Description: async content preparation request. In split mode, ingestion
prepares chunks and publishes retrieval indexing work.

Example:

```json
{
  "request_id": "ing-1",
  "response_topic": "ingestion.requests.responses.ing-1",
  "request": {
    "project_id": "p1",
    "user_id": "u1",
    "topic_id": "rentals",
    "doc_id": "d1",
    "source_uri": "memory://d1",
    "content_type": "text/plain",
    "raw_text": "hello world",
    "metadata": {
      "data_type": "project_document",
      "topic_id": "rentals",
      "collection_name": "rag_p1_v1",
      "retrieval_config": {"mode": "dense"},
      "placement_plan": {
        "placement_version": 4,
        "targets": [
          {"routing_key": "project:p1:topic:rentals", "shard_id": "retrieval-03", "collection_name": "rag_p1_v1"}
        ]
      }
    }
  }
}
```

Response:

```json
{
  "request_id": "ing-1",
  "ok": true,
  "result": {
    "job_id": "ing-1",
    "status": "completed",
    "doc_id": "d1",
    "project_id": "p1",
    "indexed_chunk_count": 1
  }
}
```

Error:

```json
{
  "request_id": "ing-1",
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "retrieval index collection_name is required",
    "retryable": false
  }
}
```

## Ingestion To Retrieval Index Queue

Topic: `retrieval.index.requests`.

Method: queue.

Structure:

```json
{
  "request_id": "string",
  "response_topic": "retrieval.index.requests.responses.<request_id>",
  "job_id": "string",
  "collection_name": "string",
  "placement_plan": {},
  "chunks": [
    {
      "document_id": "string",
      "chunk_id": "string",
      "chunk_index": 0,
      "text": "string",
      "data_type": "project_document",
      "content_hash": "string",
      "chunker_version": "string",
      "metadata": {}
    }
  ],
  "payloads": [
    {
      "payload_id": "string",
      "document_id": "string",
      "chunk_id": "string",
      "chunk_index": 0,
      "text": "string",
      "data_type": "project_document",
      "content_hash": "string",
      "embedding_version": "string",
      "chunker_version": "string",
      "metadata": {}
    }
  ],
  "retrieval_config": {}
}
```

Description: prepared chunks ready for embedding, enrichment, and vector upsert.
Ingestion waits for this response in configured split mode.

Example:

```json
{
  "request_id": "ing-1",
  "response_topic": "retrieval.index.requests.responses.ing-1",
  "job_id": "ing-1",
  "collection_name": "rag_p1_v1",
  "placement_plan": {
    "placement_version": 4,
    "targets": [
      {"routing_key": "project:p1:topic:rentals", "shard_id": "retrieval-03", "collection_name": "rag_p1_v1"}
    ]
  },
  "chunks": [
    {
      "document_id": "d1",
      "chunk_id": "d1:0",
      "chunk_index": 0,
      "text": "hello world",
      "data_type": "project_document",
      "content_hash": "sha256:abc",
      "chunker_version": "v1",
      "metadata": {"project_id": "p1", "topic_id": "rentals"}
    }
  ],
  "payloads": [],
  "retrieval_config": {"mode": "dense"}
}
```

Response:

```json
{
  "request_id": "ing-1",
  "job_id": "ing-1",
  "ok": true,
  "result": {
    "chunk_count": 1,
    "dense_enabled": true,
    "sparse_enabled": false
  }
}
```

## Project To Retrieval API

Method: local server context, queue, or HTTP.

Queue topic: `retrieval.api.requests`.

HTTP endpoints: `POST /search`, `POST /documents/delete`,
`POST /documents/raw`, `GET /health`.

Search structure:

```json
{
  "request_id": "string",
  "response_topic": "optional queue response topic",
  "operation": "search",
  "request": {
    "project_id": "string",
    "user_id": "string",
    "query_text": "string",
    "collection_name": "string",
    "retrieval_config": {},
    "retrieval_filter": {
      "project_id": "string",
      "allowed_user_ids": ["string"],
      "topic_ids": ["string"],
      "doc_ids": ["string"]
    },
    "placement_plan": {},
    "cache_key": "optional"
  }
}
```

Description: synchronous retrieval query. Project service supplies scope and
filter policy.

Example:

```json
{
  "request_id": "search-p1-u1",
  "request": {
    "project_id": "p1",
    "user_id": "u1",
    "query_text": "deployment notes",
    "collection_name": "rag_p1_v1",
    "retrieval_config": {"top_k": 5},
    "retrieval_filter": {
      "project_id": "p1",
      "allowed_user_ids": ["u1", "shared"],
      "topic_ids": ["rentals"]
    },
    "placement_plan": {
      "placement_version": 4,
      "fanout": false,
      "targets": [
        {"routing_key": "project:p1:topic:rentals", "shard_id": "retrieval-03", "collection_name": "rag_p1_v1"}
      ]
    }
  }
}
```

Search response:

```json
{
  "request_id": "search-p1-u1",
  "ok": true,
  "result": {
    "chunks": [
      {"doc_id": "d1", "chunk_id": "d1:0", "text": "hello", "score": 0.91}
    ],
    "elapsed_ms": 12,
    "cache_hit": false
  }
}
```

Delete structure:

```json
{
  "request_id": "delete-p1-d1",
  "request": {
    "project_id": "p1",
    "user_id": "u1",
    "topic_id": "rentals",
    "doc_id": "d1",
    "collection_name": "rag_p1_v1",
    "placement_plan": {
      "placement_version": 4,
      "targets": [
        {"routing_key": "project:p1:topic:rentals", "shard_id": "retrieval-03", "collection_name": "rag_p1_v1"}
      ]
    }
  }
}
```

Raw document structure:

```json
{
  "request_id": "raw-p1-d1",
  "request": {
    "project_id": "p1",
    "user_id": "u1",
    "doc_id": "d1"
  }
}
```

Raw document response:

```json
{
  "request_id": "raw-p1-d1",
  "ok": true,
  "result": {
    "found": true,
    "content_b64": "aGVsbG8=",
    "encoding": "base64"
  }
}
```

## Manager Or Project To Ingestion Status API

Method: local server context today; future HTTP/gRPC/queue transport.

Structure:

```json
{
  "request_id": "status-<job_id>",
  "request": {
    "job_id": "string"
  }
}
```

Description: status-poll for ingestion-owned job state.

Example:

```json
{
  "request_id": "status-ing-1",
  "request": {"job_id": "ing-1"}
}
```

Response:

```json
{
  "request_id": "status-ing-1",
  "ok": true,
  "result": {
    "job": {
      "job_id": "ing-1",
      "status": "completed",
      "doc_id": "d1",
      "source_uri": "memory://d1",
      "error": null,
      "metadata": {"indexed_chunk_count": 1},
      "created_at": 1710000000.0,
      "updated_at": 1710000001.0
    }
  }
}
```

## Workflow Log Event

Topic: `ingestion.events` or service-specific event topics.

Method: event queue.

Structure:

```json
{
  "event": "string",
  "job_id": "string",
  "status": "string",
  "project_id": "string",
  "user_id": "string",
  "topic_id": "string",
  "doc_id": "string",
  "metadata": {}
}
```

Description: async audit/lifecycle event. Failures must not block ingest,
index, search, or delete success.

Example:

```json
{
  "event": "ingest.completed",
  "job_id": "ing-1",
  "status": "completed",
  "project_id": "p1",
  "user_id": "u1",
  "topic_id": "rentals",
  "doc_id": "d1",
  "metadata": {"indexed_chunk_count": 1}
}
```

## Error Envelope

Structure:

```json
{
  "request_id": "string",
  "ok": false,
  "error": {
    "code": "validation_error | not_found | internal_error | unavailable",
    "message": "string",
    "retryable": false
  }
}
```

Description: common service-boundary failure shape. Queue ingestion currently
uses uppercase validation/internal codes; retrieval and ingestion APIs use
lowercase codes.

Example:

```json
{
  "request_id": "search-p1-u1",
  "ok": false,
  "error": {
    "code": "validation_error",
    "message": "missing required retrieval fields: collection_name",
    "retryable": false
  }
}
```

## Current Topic Map

| Topic | Producer | Consumer | Purpose |
| --- | --- | --- | --- |
| `ingestion.requests` | manager/project | ingestion worker | async source preparation |
| `ingestion.requests.responses.<id>` | ingestion worker | requester | ingest acceptance/completion response |
| `retrieval.index.requests` | ingestion worker | retrieval index worker | prepared chunk indexing |
| `retrieval.index.requests.responses.<id>` | retrieval index worker | ingestion worker | index completion response |
| `retrieval.api.requests` | project/manager adapter | retrieval API worker | search/delete/raw requests over queue |
| `retrieval.api.requests.responses.<id>` | retrieval API worker | requester | retrieval API response envelope |
| `ingestion.events` | services | workflow log service | lifecycle/audit events |

## Correlation Metadata

Headers:

```json
{
  "correlation_id": "same as request_id or caller trace id",
  "request_topic": "source topic for responses"
}
```

Description: trace and response routing metadata. Future broker adapters should
add idempotency key, causation ID, attempt count, visibility lease, and
dead-letter metadata.
