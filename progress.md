# Responsibility Shift Progress

Reviewed: 2026-06-30

This file only tracks the implementation of the responsibility shift:

```text
task manager = intake + status read model
task service = execution + orchestration
project service = project setup/planning
helpers = narrow capability workers
```

## Overall Progress

| Area | Progress | Completed | Missing |
| --- | ---: | --- | --- |
| Responsibility boundary | 82% | Manager, task manager, task service, project planning, and helper ownership are split in code; generated gRPC stubs moved to `shared.transport.grpc.generated`; project service no longer imports retrieval internals; retrieval ingest compatibility pipeline and project schema aliases were removed. | Keep tightening import-boundary coverage as service-owned modules evolve. |
| Task manager intake/status | 80% | Task manager consumes intake, publishes only `task.requests`, consumes `task.events`/`task.results`, and writes Redis status through the shared status store contract. | Add stronger live-runtime coverage for Redis updates from real task-service events. |
| Task service executor | 75% | `task_service` owns project plan dispatch, helper fan-out/fan-in, retries, dead letters, final result publication, and SQLite execution state. | Add production-grade lease/backoff/retry timing and broader crash-recovery coverage. |
| Project planning boundary | 85% | Project planning uses canonical `project.plan.requests/results`; old `domain.project.*` runtime aliases were removed from shared topics, config, task-service consumers, and tests; placement scope is project-owned and serialized through plan payloads. | Keep plan payloads JSON-safe as new project capabilities are added. |
| Helper ownership | 75% | Ingestion, retrieval, retrieval-index, storage, and SQLite node worker/helper paths exist and consume helper topics; old retrieval ingest compatibility code that embedded ingestion/project adapter behavior was deleted. | Keep import-boundary tests strict as helper command contracts evolve. |
| Execution state ownership | 70% | SQLite task-service state repository persists helper expectations, helper results, retry plans, and final publication markers. | Decide whether to split `task_states` into explicit execution/step tables. |
| Status read model | 75% | Redis `TaskStatusRecord`, TTL writes, and status reads exist; task manager updates status from task events/results. | Add more live Redpanda + Redis status transition coverage. |
| Local runtime | 70% | Local broker-first runner starts manager, task manager, task service, project service, helper workers, Redis, Redpanda, Qdrant, storage, SQLite node, and workflow log. | Add stricter readiness assertions around full ingest/search flows. |
| Tests | 75% | Focused tests now assert task-manager intake/status-only behavior, task-service helper orchestration, project planning topics, service import boundaries, and broker-first integration flow. | Continue moving broad legacy tests under owning service folders. |

## Steps

| Step | Topic | Implementation | Acceptance Standard | Status |
| ---: | --- | --- | --- | --- |
| 1 | Replace planning docs | Replace original broad `plan.md` and `progress.md` with responsibility-shift-only implementation docs. | Both docs focus only on task manager, task service, project planning, helper ownership, status, and graphs. | Complete |
| 2 | Add task boundary topics | Add canonical topics for `task.requests`, `task.events`, `project.plan.requests`, and `project.plan.results`; remove obsolete `domain.project.*` runtime topics. | Topic constants exist and broker bootstrap creates only canonical project-planning topics. | Complete |
| 3 | Add task boundary contracts | Add typed shared contracts for task requests, task events, task results, project plan requests, and project plan results. | Contracts are transport-neutral, validated, and covered by unit tests. | Complete |
| 4 | Create task service package | Add `task_service/` package, settings, app context, worker, repository, dispatcher, and tests. | Task service starts independently and consumes `task.requests`. | Complete |
| 5 | Move orchestration code | Move project-plan dispatch, helper fan-out/fan-in, follow-up scheduling, retries, dead letters, and final result publication out of `task_manager_service`. | Helper commands are published by task service in normal runtime. | Complete |
| 6 | Move execution state | Move `task_states` repository ownership to task service and add execution/step tables if required. | Task service restart preserves in-flight execution state; task manager restart does not affect execution. | In progress |
| 7 | Reduce task manager code | Strip task manager normal path down to raw task intake, request normalization, `task.requests` publication, status event/result consumption, Redis updates, and status reads. | Task manager normal code has no helper command topic references. | Complete |
| 8 | Recontract project planning | Use only `project.plan.requests/results` for project planning; remove `domain.project.commands/results` runtime aliases. | Project service returns JSON-safe project plans; it does not publish helper commands. | Complete |
| 9 | Keep helpers narrow | Validate ingestion, retrieval, retrieval-index, storage, and SQLite/database helpers only consume their helper commands and return helper results. | Helpers do not import task manager, task service, or project internals. | Pending |
| 10 | Update Redis status flow | Update task manager to consume `task.events` and `task.results` and upsert Redis task status. | Redis status reflects accepted/running/failed/completed states from task-service messages. | Pending |
| 11 | Update local runtime | Start task manager/intake and task service/executor separately in broker-first local runtime. | Local startup validates both processes and runs ingest/search through the new split. | In progress |
| 12 | Rewrite tests | Move old task-manager orchestration tests under task-service coverage and add task-manager intake/status-only tests. | Tests assert sender/receiver ownership for every topic. | In progress |
| 13 | Remove compatibility orchestration | Remove old task-manager helper dispatch after task-service path passes. | `task_manager_service` cannot create ingestion/retrieval/storage/index helper commands in normal runtime. | Complete |

## Graphs

### Current State To Replace

```mermaid
flowchart LR
    C[Client] -->|RPC| M[Current Manager]
    M -->|task.intake| B[(Redpanda)]
    B --> TM[Task Manager]
    TM -->|task.requests| B
    B --> P[Project Service]
    P -->|project.plan.results| B
    B --> TM
    TM -->|helper.ingestion.commands| B
    TM -->|helper.retrieval.commands| B
    TM -->|helper.storage.commands| B
    TM -->|helper.retrieval_index.commands| B
    TM --> Redis[(Redis Status)]

    classDef wrong fill:#ffe8e8,stroke:#b00020,color:#111;
    class TM wrong;
```

### Target Structure

```mermaid
flowchart LR
    C[Client] -->|RPC| TM[Task Manager / Intake + Status]
    TM -->|task.requests| B[(Redpanda)]
    B --> TS[Task Service / Executor]

    TS -->|project.plan.requests| B
    B --> P[Project Service / Planning]
    P -->|project.plan.results| B
    B --> TS

    TS -->|helper commands| B
    B --> I[Ingestion Helper]
    B --> R[Retrieval Helper]
    B --> RI[Retrieval Index Helper]
    B --> S[Storage Helper]
    B --> DB[SQLite / DB Helper]

    I -->|helper result| B
    R -->|helper result| B
    RI -->|helper result| B
    S -->|helper result| B
    DB -->|helper result| B
    B --> TS

    TS -->|task.events / task.results| B
    B --> TM
    TM --> Redis[(Redis Status Read Model)]
    TM -->|status RPC| C

    B -. audit.events .-> W[Workflow Log]
```

### Target Ingest Sender Receiver Flow

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant TM as Task Manager
    participant B as Redpanda
    participant TS as Task Service
    participant P as Project Service
    participant I as Ingestion Helper
    participant S as Storage Helper
    participant RI as Retrieval Index Helper
    participant Redis as Redis

    C->>TM: ingest request
    TM->>Redis: accepted status
    TM->>B: task.requests
    B->>TS: task request
    TS->>B: task.events running
    B->>TM: task event
    TM->>Redis: running status
    TS->>B: project.plan.requests
    B->>P: plan request
    P->>B: project.plan.results
    B->>TS: project plan
    TS->>B: helper.ingestion.commands
    B->>I: ingestion command
    I->>B: helper.ingestion.results
    B->>TS: ingestion result
    TS->>B: helper.storage.commands
    TS->>B: helper.retrieval_index.commands
    B->>S: storage command
    B->>RI: index command
    S->>B: helper.storage.results
    RI->>B: helper.retrieval_index.results
    B->>TS: helper results
    TS->>B: task.results completed
    B->>TM: task result
    TM->>Redis: completed status with TTL
```

### Target Search Sender Receiver Flow

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant TM as Task Manager
    participant B as Redpanda
    participant TS as Task Service
    participant P as Project Service
    participant R as Retrieval Helper
    participant Redis as Redis

    C->>TM: search request
    TM->>Redis: accepted status
    TM->>B: task.requests
    B->>TS: task request
    TS->>B: task.events running
    B->>TM: task event
    TM->>Redis: running status
    TS->>B: project.plan.requests
    B->>P: plan request
    P->>B: project.plan.results
    B->>TS: project plan
    TS->>B: helper.retrieval.commands
    B->>R: retrieval command
    R->>B: helper.retrieval.results
    B->>TS: retrieval result
    TS->>B: task.results completed
    B->>TM: task result
    TM->>Redis: completed status with TTL
```
