# Development Progress

Reviewed: 2026-06-24


### Target Architecture Graph

```mermaid
flowchart LR
    Client[Client / SDK] --> Manager[Manager / Auth Server]

    Broker[(Redpanda Broker)]

    Manager <--> Broker
    Project[Project Domain Service] <--> Broker
    Workflow[Workflow Logging Service] <--> Broker
    Other[Other Domain Services] <--> Broker
    TaskManager[Task Manager Service] <--> Broker
    Ingestion[Ingestion Helper Node] <--> Broker
    Retrieval[Retrieval Helper Node] <--> Broker
    Storage[Storage Helper Node] <--> Broker
    TaskManager --> Redis[(Redis Task Status Store)]
    Manager --> Redis
```

### Ingest And Index Task

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant M as Manager / Auth
    participant B as Redpanda
    participant P as Project Domain
    participant I as Ingestion Helper
    participant S as Storage Helper
    participant R as Retrieval Index Helper
    participant T as Task Manager
    participant Redis as Redis Status Store

    C->>M: ingest request
    M->>B: publish task intake
    B->>T: consume task intake
    T->>Redis: write accepted/running status by task_id
    T->>B: publish domain.project.commands
    B->>P: consume project command
    P->>B: publish domain.project.results
    B->>T: consume project plan/result
    T->>B: publish helper.ingestion.commands
    B->>I: consume ingestion command
    I->>B: publish helper.storage.commands, if raw storage is needed
    B->>S: consume storage command
    S->>B: publish helper.storage.results
    I->>B: publish helper.ingestion.results
    B->>T: consume helper result events
    T->>B: publish helper.retrieval_index.commands
    B->>R: consume index command
    R->>B: publish helper.retrieval_index.results
    B->>T: consume helper result events
    T->>Redis: write final task status by task_id with TTL
    T->>B: publish task.results
    M->>Redis: read status by task_id
    M-->>C: accepted/status/final result response
```

### Search Task

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant M as Manager / Auth
    participant B as Redpanda
    participant P as Project Domain
    participant R as Retrieval Helper
    participant T as Task Manager
    participant Redis as Redis Status Store

    C->>M: search request
    M->>B: publish task intake
    B->>T: consume task intake
    T->>Redis: write accepted/running status by task_id
    T->>B: publish domain.project.commands
    B->>P: consume project command
    P->>B: publish domain.project.results
    B->>T: consume project plan/result
    T->>B: publish helper.retrieval.commands
    B->>R: consume retrieval command
    R->>B: publish helper.retrieval.results
    B->>T: consume helper result event
    T->>Redis: write final task status by task_id with TTL
    T->>B: publish task.results
    M->>Redis: read status by task_id
    M-->>C: accepted/status/final result response
```

### Delete Task

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant M as Manager / Auth
    participant B as Redpanda
    participant P as Project Domain
    participant R as Retrieval Helper
    participant S as Storage Helper
    participant T as Task Manager
    participant Redis as Redis Status Store

    C->>M: delete request
    M->>B: publish task intake
    B->>T: consume task intake
    T->>Redis: write accepted/running status by task_id
    T->>B: publish domain.project.commands
    B->>P: consume project command
    P->>B: publish domain.project.results
    B->>T: consume project plan/result
    T->>B: publish helper.retrieval.commands
    T->>B: publish helper.storage.commands, if raw delete is needed
    B->>R: consume retrieval command
    B->>S: consume storage command
    R->>B: publish helper.retrieval.results
    S->>B: publish helper.storage.results
    B->>T: consume helper result events
    T->>Redis: write final task status by task_id with TTL
    T->>B: publish task.results
    M->>Redis: read status by task_id
    M-->>C: accepted/status/final result response
```

### Status Task

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant M as Manager / Auth
    participant Redis as Redis Status Store

    C->>M: status request
    M->>Redis: read status by task_id
    M-->>C: task status response
```

### Workflow Log Task

```mermaid
sequenceDiagram
    autonumber
    participant C as Client or Service Event
    participant M as Manager / Auth
    participant B as Redpanda
    participant W as Workflow Logging Domain
    participant T as Task Manager
    participant Redis as Redis Status Store

    C->>M: workflow log query or event request
    M->>B: publish task intake
    B->>T: consume task intake
    T->>B: publish domain.workflow_log.commands
    B->>W: consume workflow command
    W->>B: publish domain.workflow_log.results
    W->>B: publish audit.events
    B->>T: consume workflow result event
    T->>Redis: write task status by task_id
    T->>B: publish task.results, when final result exists
    M->>Redis: read status by task_id, when request/response is needed
    M-->>C: workflow response, when client initiated
```

### Required Runtime Shape

```mermaid
flowchart TB
    Local[Local Machine] --> M[Manager server]
    Local --> T[Task manager server]
    Local --> P[Project service server]
    Local --> D[Other domain service servers]
    Local --> I1[Ingestion worker server]
    Local --> I2[Additional ingestion worker server]
    Local --> RA[Retrieval API server]
    Local --> RI[Retrieval index worker server]
    Local --> S1[Storage node]
    Local --> SQL[SQLite small DB node]
    Local --> Redis[Redis task-status node]
    Local --> B[Redpanda broker]
    Local --> W[Workflow log server]

    Prod[Production] --> PM[Same manager code]
    Prod --> PP[Same project code]
    Prod --> PI[Same ingestion code]
    Prod --> PR[Same retrieval code]
    Prod --> PB[Same Redpanda broker contract]

    Local -.differs only by config addresses.-> Prod
```
