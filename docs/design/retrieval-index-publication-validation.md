# Retrieval Index Publication Validation

Section status: implementation accepted for the seventh development loop section.

## Requirement Document

Ingestion can now publish prepared chunks to `retrieval.index.requests`, but the
publication payload can have an empty `collection_name`. That is acceptable for
tests proving the shape, but it is not a valid indexing command. The worker
should fail fast when retrieval publication is configured without enough routing
metadata to produce a usable command.

This section validates indexing publication inputs at the ingestion boundary.
Compatibility-only ingestion remains unchanged when no retrieval queue is
configured.

Scope:

- Require `collection_name` when publishing to the retrieval index queue.
- Preserve optional `retrieval_config` metadata.
- Return a structured failure response if publication metadata is incomplete.
- Keep no-queue compatibility behavior unchanged.

Out of scope:

- Resolving collection names from project config.
- Defining project policy clients.
- Retrying or dead-lettering failed index publications.

## Acceptance Criteria

- If `retrieval_queue` is configured and `collection_name` is missing, queued
  ingestion returns `ok: false` with a validation error.
- If `retrieval_queue` is configured and `collection_name` is present, the
  published indexing command includes that collection name.
- No-retrieval-queue compatibility ingestion still succeeds without
  `collection_name`.
- Tests cover success, validation failure, and compatibility behavior.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
ingestion_service/server/
  consumer.py        publication validation

tests/
  test_ingestion_service_server.py

docs/
  design/retrieval-index-publication-validation.md

progress.md
```

## Implementation Design

1. Validate `collection_name` in `_index_request_payload(...)`.
2. Keep `ValueError` classified as a non-retryable validation failure.
3. Update existing publication test to include a collection name.
4. Add a failure test for missing collection name with retrieval queue enabled.
5. Run focused ingestion and retrieval-index tests.

## Review Checklist

- Validation applies only when retrieval publication is enabled.
- The error response is structured consistently with existing ingest failures.
- No unrelated project config lookup is introduced.
