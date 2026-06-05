# Overview

`qdrant_rag_server` is an async, project-scoped information retrieval service.

Despite the repository name, the project should not be treated as only a RAG server. The core service is retrieval-first:

- ingest source data
- parse and chunk data through adapters
- embed and index chunks
- retrieve filtered chunks
- optionally rerank results
- optionally generate an answer using a request-scoped LLM key
- track ingest status
- delete indexed documents
- preserve raw source content when storage is configured

## Current Status

The repository is a prototype and core scaffold. It has useful pieces, but it is not production-ready.

Implemented:

- core project/user/KB/document/chunk models
- default KB behavior with `kb_id = "default"` when callers omit KB separation
- project adapter interface and website adapter prototype
- SQLite project config repository
- gateway request validation and server-built retrieval filters
- Qdrant vector store wrapper
- async search pipeline with optional reranking
- async ingest workers with in-memory status
- memory/filesystem/S3-compatible object storage abstractions
- Tier-1 retrieval cache and Tier-2 SQLite generation-response cache
- gRPC service boundary
- health and metrics scaffold
- embedding collection version manager
- opt-in OpenRouter generation client

Known gaps:

- SQLite and filesystem paths still do blocking work inside async methods.
- Ingest jobs are not durable.
- Ingest queue is unbounded.
- Raw content still enters through `metadata["raw_text"]`.
- Website adapter config is hard-coded.
- Retrieval is still vector-first; BM25/hybrid need a retriever framework.
- Data types need a registry so each type can own schema, filters, and retrieval defaults.
- Generation cache keys do not yet include all model/generation parameters.

## Minimal Target

The next stable milestone is:

```text
Minimal safe information retrieval core:
project/user-scoped ingest, search, delete, cache invalidation, and raw backup.
```

Avoid expanding into a broad platform before this is solid. In particular, do not add organization-wide tenancy, complex RBAC, distributed schedulers, or full observability until the core retrieval service is safe and replaceable.

## Core Concepts

### Project

A project is the top-level retrieval scope. Qdrant collections are named by project and active embedding version:

```text
rag_{project_id}_{active_embedding_version}
```

### User And Shared Data

Private records use the real `user_id`.

Shared project records use:

```text
__shared__
```

Search can include both the requester and shared records when `include_shared` is true.

### Knowledge Base

`kb_id` is an optional grouping label inside a project/user scope. If missing or blank, the service uses:

```text
default
```

Callers only need custom KB IDs when they intentionally want to search selected groups.

### Data Type

`data_type` identifies the purpose or schema of a record, such as:

```text
project_document
agent_memory
running_record
case_note
```

The current payload model carries `data_type`, but gateway/search filtering has not fully exposed it yet.

### Retriever

Vector search is implemented now. The target architecture should allow retrievers such as:

- vector
- BM25
- hybrid vector + BM25
- metadata lookup
- future graph or relationship lookup

Retrievers should return a shared result shape so the engine can merge and optionally rerank candidates.
