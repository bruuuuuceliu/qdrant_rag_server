# Manager Split-Client Composition

Section status: implementation accepted for the twelfth development loop section.

## Requirement Document

`ManagerService` now accepts explicit ingestion and retrieval clients, but the
manager app composition root still builds it from a combined
`ProjectDocumentClient`. That leaves the boundary split in the service class but
not yet in the manager bootstrap. The next small step is to wire the manager
app through the split adapters at composition time.

This section keeps the compatibility project client in place for local and gRPC
bootstrap, but the `ManagerService` constructor call should receive explicit
ingestion and retrieval clients.

Scope:

- Update `manager_service.server.app.create_app` to pass split clients.
- Keep compatibility project client composition unchanged.
- Keep queue behavior unchanged.

Out of scope:

- Remote ingestion or retrieval transport.
- Removing `ProjectDocumentClient` compatibility adapters.
- Wiring retrieval service internals into the manager app.

## Acceptance Criteria

- Manager bootstrap constructs `ManagerService` with explicit ingestion and
  retrieval clients.
- Compatibility `ProjectDocumentClient` remains available as a composition aid.
- Existing manager app tests still pass.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
manager_service/server/
  app.py             split-client composition

tests/
  test_manager_service.py

docs/
  design/manager-split-client-composition.md

progress.md
```

## Implementation Design

1. Update manager app bootstrap to build explicit ingestion/retrieval adapters
   from the project client.
2. Pass those adapters to `ManagerService`.
3. Update tests to assert the explicit split clients are present.
4. Run manager app and manager service tests.

## Review Checklist

- The bootstrap change does not alter compatibility behavior.
- The split client wiring is explicit and local to the manager composition root.
- No infrastructure factories are added.
