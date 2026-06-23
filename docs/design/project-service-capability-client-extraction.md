# Project Service Capability Client Extraction

Status: accepted.

## Requirement

Project-document task orchestration should not know compatibility `RagEngine`
method names. The project service should own planning and call typed
project-facing capability clients for ingestion and retrieval/database work.

## Implemented

- Added `project_service.capabilities` with:
  - `ProjectIngestionCapability`
  - `ProjectRetrievalCapability`
  - `CompatibilityIngestionCapability`
  - `CompatibilityRetrievalCapability`
- Refactored `ProjectDocumentTaskService` to call only capability methods:
  - `start_ingest(plan)`
  - `get_status(job_id)`
  - `search(plan)`
  - `delete_document(plan)`
- Kept temporary `RagEngine` method mapping inside compatibility adapters.
- Updated `LocalProjectServiceClient` to accept typed capability clients while
  defaulting to compatibility adapters for local runtime.
- Exported the capability contracts from `project_service`.

## Remaining Work

- Replace compatibility ingestion adapters with a generic ingestion submission
  transport for normal routes.
- Replace remote compatibility gRPC with project task APIs.
- Remove `raw_plan` fields after no compatibility adapter needs them.

## Verification

- `pytest tests/test_project_tasks.py tests/test_project_service_client.py tests/test_project_planning.py -q`
- `pytest tests/test_project_tasks.py tests/test_project_service_client.py tests/test_project_planning.py tests/test_manager_service.py tests/test_manager_import_boundaries.py -q`
