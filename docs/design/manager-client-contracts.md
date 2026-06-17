# Manager Client Contracts

Section status: implementation accepted for the first development loop section.

## Requirement Document

The manager service must express the same ownership boundaries in code that the
router already expresses in route decisions. A `project_document` ingest or
status request belongs to ingestion. A `project_document` search or delete
request belongs to retrieval. The current implementation routes all executable
operations through one `ProjectDocumentClient`, which is useful during migration
but hides the final service boundary.

This section introduces service-specific manager-facing client contracts while
preserving current behavior. The implementation must remain compatible with the
existing local and remote project/RAG client until independent ingestion and
retrieval servers are implemented.

Scope:

- Add manager-facing ingestion and retrieval client protocols.
- Keep `ProjectDocumentClient` as a compatibility protocol.
- Add small compatibility adapters from `ProjectDocumentClient` to the new
  service-specific protocols.
- Update `ManagerService` to call ingestion and retrieval clients based on the
  route owner.
- Keep queue-backed ingest behavior unchanged.
- Keep config and environment behavior unchanged for this section.

Out of scope:

- Creating independent ingestion or retrieval network servers.
- Moving ingest execution out of `ProjectDocumentClient`.
- Adding production broker semantics.
- Implementing memory service or workflow-log query routes.

## Acceptance Criteria

- `ManagerService.ingest` uses an ingestion client for direct ingest when no
  queue is configured.
- `ManagerService.ingest_status` uses an ingestion client.
- `ManagerService.search` uses a retrieval client.
- `ManagerService.delete` uses a retrieval client.
- Existing callers can still construct `ManagerService(project_documents=...)`
  and get the same behavior through compatibility adapters.
- New callers can construct `ManagerService(ingestion=..., retrieval=...)`
  without providing a combined project-document client.
- Queue-backed ingest remains compatible with `ingestion_service.server`, which
  still accepts a project-document client during the migration.
- Tests cover the new client split and the compatibility path.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
manager_service/
  clients.py          service-specific protocols and compatibility adapters
  service.py          route dispatch through ingestion/retrieval clients
  __init__.py         public exports

tests/
  test_manager_service.py

docs/
  design/manager-client-contracts.md

progress.md
```

No new config file is needed because this section changes only in-process
manager composition. Future sections will add config when new physical service
clients are introduced.

## Class Design

### `IngestionClient`

Manager-facing protocol for document ingestion ownership.

Methods:

- `ingest(request) -> Any`
- `ingest_status(job_id) -> Any`

### `RetrievalClient`

Manager-facing protocol for retrieval ownership.

Methods:

- `search(request) -> Any`
- `delete_document(request) -> Any`

### `ProjectDocumentClient`

Compatibility protocol that keeps the existing local and remote project/RAG
client usable during migration.

### `ProjectDocumentIngestionClient`

Small adapter that implements `IngestionClient` by delegating to a
`ProjectDocumentClient`.

### `ProjectDocumentRetrievalClient`

Small adapter that implements `RetrievalClient` by delegating to a
`ProjectDocumentClient`.

### `ManagerService`

Constructor accepts either:

- explicit `ingestion` and `retrieval` clients, or
- a compatibility `project_documents` client that is adapted internally.

Runtime methods call the service-specific clients only. The compatibility client
is retained as a construction aid and migration marker.

## Implementation Design

1. Add protocol and adapter classes in `manager_service.clients`.
2. Update `ManagerService.__init__` to accept optional `ingestion` and
   `retrieval` clients.
3. If a compatibility `project_documents` client is provided, use it to fill any
   missing service-specific clients through adapters.
4. Reject construction when either required executable client is missing.
5. Update manager operation methods to dispatch to `_ingestion` and
   `_retrieval`.
6. Update public exports.
7. Add tests for explicit split-client construction and compatibility adapter
   construction.
8. Run focused manager tests, then run a broader relevant test set.

## Review Checklist

- Manager routing and manager dispatch agree on owner service names.
- Compatibility adapters contain all calls to the combined project-document
  client inside `manager_service.clients` and composition roots.
- No parser, Qdrant, embedding, ingestion handler, or RAG engine internals are
  imported by `manager_service.service`.
- The implementation remains minimal and does not introduce future network
  client complexity before the physical services exist.
