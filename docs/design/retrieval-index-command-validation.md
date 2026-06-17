# Retrieval Index Command Validation

Section status: implementation accepted for the thirteenth development loop section.

## Requirement Document

Ingestion now validates `collection_name` before publishing retrieval indexing
requests, but `RetrievalIndexCommand` itself still accepts an empty collection
name. That leaves other future publishers able to enqueue commands that cannot
be executed safely by retrieval indexing workers.

This section moves command-level validation into the retrieval indexing command
parser so every queue publisher is held to the same minimum contract.

Scope:

- Require non-empty `collection_name` in `RetrievalIndexCommand.from_payload`.
- Keep empty chunk lists valid.
- Preserve existing successful command parsing behavior.
- Return a structured failure response from the consumer when validation fails.

Out of scope:

- Project config lookup for collection names.
- Broker retry or dead-letter handling.
- Transport changes.

## Acceptance Criteria

- `RetrievalIndexCommand.from_payload(...)` raises `ValueError` when
  `collection_name` is missing or blank.
- Existing valid command payloads still parse.
- `RetrievalIndexConsumer` publishes an `ok: false` response for invalid command
  payloads when a response topic is available.
- Tests cover valid parsing and invalid command response behavior.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
retrieval_service/indexing/
  commands.py        collection validation
  consumer.py        parse failure response handling

tests/
  test_retrieval_index_consumer.py

docs/
  design/retrieval-index-command-validation.md

progress.md
```

## Implementation Design

1. Validate collection name in `RetrievalIndexCommand.from_payload`.
2. Update consumer error handling so parse errors can still publish responses.
3. Add invalid-command consumer test.
4. Run retrieval indexing and ingestion publication tests.

## Review Checklist

- Validation applies in retrieval-owned command code.
- Consumer can respond to malformed commands without crashing its run loop.
- No project-service dependency is introduced.
