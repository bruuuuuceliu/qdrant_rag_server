# Agent Memory Service — Implementation Design

Status: **Approved for implementation** — companion to
`docs/agent-memory-requirements.md` (the authoritative contract). This doc
specifies the concrete implementation for both repos.
Date: 2026-08-02
Owner: this repository (the RAG service) + Simple Agent wiring
Version: 1.0

---

## 1. Goals and Non-Goals

**Goals**

- Stand up `memory_service` as a broker-first domain service consuming
  `domain.memory.commands` and replying on `domain.memory.results`, mirroring
  `workflow_log_service`.
- Own the durable SQLite store for sessions, messages, memory summaries, user
  profiles, and versioned facts.
- Hand vector indexing and semantic search for memory to `retrieval_service`
  (which already owns the memory schemas), over the broker.
- Wire `simple_agent`'s conversation-server with a memory client adapter
  (fake for local/tests, broker-backed for production) that records
  sessions/messages, triggers compression at context limits, and injects
  lookup/profile data into the chat context.
- Keep everything runnable/testable without a real broker or real simple_agent
  using the same production code paths (dependency-injected ports, not
  separate fake-only logic).

**Non-goals (explicit, per requirements §2.4)**

- Model-backed summarization, passive fact extraction, retention/TTL, a
  `history.replay` operation, and a manager gRPC route for `agent_memory`.

---

## 2. Shared Contract Additions

What already exists (no change): topics `domain.memory.commands` /
`domain.memory.results`; `DataType.AGENT_MEMORY`; `MessageEnvelope`;
`DomainCommandPayload`/`DomainResultPayload`; the retrieval memory schemas and
helper topics.

What must be added/changed (status as of the implementation):

| # | Change | File | Detail | Status |
| --- | --- | --- | --- | --- |
| C1 | Mark `AGENT_MEMORY` executable | `shared/contracts/data_types.py` | `DataTypeSpec(..., executable=True)`; drop `reserved_reason`. | **Done** |
| C2 | Add identity event topic | `shared/contracts/topics.py` | Add `identity_user_events: str = "identity.user.events"` to `TopicSet`. | **Done** |
| C3 | Add service-token verification helper | `shared/service_auth.py` (new) | Mirror of `simple_agent_service_auth.verify_service_token` (HS256, claims `iss/aud/svc/actor_user_id/actor_role`), same constants. Small standalone module so `memory_service` can verify callers without importing a Simple Agent service package. Note: after the repos fully merge this collapses to one module. | **Done** |
| C4 | (Optional) `error_code` on `DomainResultPayload` | `shared/contracts/task_messages.py` | NOT required in v1 — the structured code is carried in `result.error.code` and mirrored via existing `error`/`retryable` fields. Revisit if retry orchestrators need envelope-level codes. | Deferred |
| C5 | New retrieval helper operations | `retrieval_service/` | `memory_ingest` on `helper.retrieval_index.commands`; `memory_search` on `helper.retrieval.commands` (see §4). | **Done** |

No new `MessageType` values are required (`DOMAIN_COMMAND`/`DOMAIN_RESULT`,
`HELPER_COMMAND`/`HELPER_RESULT` cover the flows).

---

## 3. memory_service Structure (file-by-file)

Mirrors `workflow_log_service` exactly. New package `memory_service/`:

```
memory_service/
  __init__.py                  # public exports (mirror workflow_log_service/__init__.py)
  config.py                    # MemoryServiceSettings (env-driven, mirror WorkflowLogDomainSettings)
  models.py                    # frozen dataclasses: MemorySession, MemoryMessage, MemoryRecord,
                               #   UserProfile, UserFact, IdempotencyRecord, CompressionSpan
  repository.py                # MemoryRepository Protocol + MemoryInMemoryRepository +
                               #   SQLiteMemoryRepository (initialize schema from §6 of requirements)
  compression.py               # CompressionPolicy Protocol + CondenseV1Policy (deterministic)
  identity.py                  # IdentitySource Protocol + FakeIdentitySource + BrokerIdentitySource
  indexer.py                   # MemoryIndexer Protocol + BrokerMemoryIndexer (helper command publisher)
  searcher.py                  # MemorySearcher Protocol + BrokerMemorySearcher (helper command request/reply)
  domain_handler.py            # MemoryDomainHandler: dispatch the 8 operations (requirements §7)
  domain_app.py                # MemoryDomainServerContext + create_domain_app / create_default_domain_app
  worker.py                    # process entrypoint (mirror workflow_log_service/worker.py)
```

### 3.1 `models.py`

Frozen dataclasses with explicit `from_mapping`/`to_mapping` converters (a
cleaner convention than `WorkflowLogEntry`'s single `from_message`, chosen so
the models round-trip through the broker payloads).
Fields correspond exactly to the requirements §6 tables plus transport fields:

- `MemorySession(session_id, owner_user_id, agent_id, status, started_at,
  closed_at, metadata, created_at, updated_at)`
- `MemoryMessage(message_id, session_id, owner_user_id, agent_id, role,
  sequence_number, content, created_at, metadata)`
- `MemoryRecord(memory_id, session_id, owner_user_id, agent_id, kind, content,
  covered_from, covered_to, created_at)`
- `UserProfile(user_id, basic_info, identity_revision, created_at, updated_at)`
- `UserFact(fact_id, user_id, fact_type, subject, text, status, version,
  superseded_by, updated_by, source_message_id, created_at, updated_at)`
- `IdempotencyRecord(idempotency_key, operation, request_hash, result,
  created_at)`

### 3.2 `repository.py`

- `MemoryRepository(Protocol)`: `upsert_session`, `get_session`,
  `close_session`, `insert_message` (returns `recorded: bool`),
  `get_message`, `list_session_messages`, `insert_memory_record`,
  `get_memory_record`, `upsert_profile`, `get_profile`,
  `list_active_facts`, `list_facts`, `supersede_fact` (transactional FR-4.5),
  `get_or_store_idempotent` (transactional §9 replay).
- `MemoryInMemoryRepository`: dict-backed, same interface (unit tests).
- `SQLiteMemoryRepository`: `sqlite3` with the DDL from requirements §6;
  `initialize()` runs `executescript`. All mutation+idempotency writes commit
  in a single transaction (`BEGIN IMMEDIATE`).

`supersede_fact(user_id, fact_type, subject, new_fact)` transaction:
1. `SELECT ... WHERE user_id=? AND fact_type=? AND subject=? AND status='active'`.
2. Mark each `status='inactive'`, `superseded_by=new_fact_id`.
3. `version = 1 + COALESCE(MAX(version) OVER same key, 0)`.
4. `INSERT ... status='active'`.
5. Unique-index violation → rollback → raise `FactSupersessionConflict`
   (mapped to `conflict`/409).

### 3.3 `compression.py`

`CompressionPolicy(Protocol)` with `async compress(span: CompressionSpan) ->
CondensedOutput` and a `policy_name` attribute.

`CondenseV1Policy` (deterministic, idempotent):
- Input: ordered `[(sequence_number, role, content)]` within
  `[start_sequence, end_sequence]`; `keep_recent` newest kept verbatim.
- For each older message, emit a fixed-shape line:
  `[seq] role: first_sentence… last_sentence` where `first_sentence`/
  `last_sentence` are the first/last up-to-240-char sentence splits of
  `content` (split on `.`, `!`, `?`), preserving order.
- Join lines with `\n`. Deterministic pure function of the input — same span +
  policy ⇒ same output. Model-backed summarizer is a future
  `ModelSummaryPolicy` behind the same protocol (different `policy_name`).

`memory_id` for a compression span is derived by the handler:
`"mem_sum_" + sha256(canonical("{session_id}|{from}|{to}|{policy}"))[:24]`.

### 3.4 `identity.py`

`IdentitySource(Protocol)`:
- `async on_user_registered(event) -> UserProfile` — apply an
  `identity.user.registered` event (no `.v1` suffix; the separate
  `event_version: 1` field carries versioning) to the profile (create/refresh
  `basic_info`, set `identity_revision`).
- `async on_user_status_changed(event) -> UserProfile | None` — reconcile
  `role`/`account_status`.

`BrokerIdentitySource`: consumes `identity.user.events` (group
`memory_service.identity`) and calls the above. Payloads follow the extended
identity outbox event (§5.3).

`FakeIdentitySource`: deterministic seeded users (e.g. `user_1`, `user_2` with
fixed email/display_name/role/account_status), used when
`MEMORY_IDENTITY_MODE=fake`. Production uses `broker` mode. Direct cross-DB
reads (requirements §5) are a documented backfill tool implemented as a
`DirectReadIdentitySource` follow-up, not required in v1.

### 3.5 `indexer.py` / `searcher.py`

Two thin ports so the domain handler never touches the broker directly:

- `MemoryIndexer(Protocol)`: `async index(records: list[MemoryRecord]) -> None`
  (fire-and-forget). `BrokerMemoryIndexer` publishes a `HELPER_COMMAND`
  (`operation="memory_ingest"`) to `helper.retrieval_index.commands` with
  `MemoryChunkPayload`-shaped payloads and a `response_topic` of
  `helper.retrieval_index.results`; does not await. `FakeMemoryIndexer` records
  calls.
- `MemorySearcher(Protocol)`: `async search(scope, query, top_k) ->
  list[dict]` (semantic chat-history hits). `BrokerMemorySearcher` publishes a
  `HELPER_COMMAND` (`operation="memory_search"`) to `helper.retrieval.commands`,
  awaits the matching `HELPER_RESULT` on `helper.retrieval.results` by
  `correlation_id`. `FakeMemorySearcher` returns deterministic hits.

Broker request/reply in `BrokerMemorySearcher` reuses the existing helper
result topic and matches on `correlation_id`; it shares the memory_service
producer and adds a consumer for the results topic in the domain app (§3.7).

### 3.6 `domain_handler.py`

`MemoryDomainHandler(repository, *, compression, indexer, searcher,
identity_source, producer, service_auth_settings, allowed_services)`.

- `handle(envelope)`: parse `DomainCommandPayload`, verify service identity
  (§8 of requirements), derive `owner_user_id`/`agent_id`, dispatch to the 8
  operation methods, build the DOMAIN_RESULT, and publish to the response
  topic (default `domain.memory.results`, override from
  `context.response_topic`) keyed by `task_id`.
- Ownership/scope enforcement is centralized: every operation receives a
  `RequestScope(owner_user_id, agent_id)`; repository calls always pass it.
- Error mapping: catch `ValueError`/validation → `validation_error`;
  `MemoryNotFoundError` → `not_found`; `FactSupersessionConflict`/idempotency
  mismatch → `conflict`; `Indexer/Searcher/Identity` transport errors →
  `upstream_error`/`unavailable`; unexpected → `internal_error`. Each sets
  `result={"ok": false, "error": {"code","message","retryable"}}` and mirrors
  `error`/`retryable` at the envelope level.

Per-operation behavior:

| operation | flow |
| --- | --- |
| `session.start` | idempotent upsert; returns session |
| `message.record` | insert with dedup; after commit, fire-and-forget `indexer.index([MemoryRecord(kind='message')])`; `indexed` reflects whether the hand-off was queued |
| `session.close` | set closed |
| `memory.compress` | load span messages, `compression.compress(...)`, deterministic `memory_id`, persist `MemoryRecord(kind='compression_summary')` (dedup by `memory_id`), fire-and-forget index, return condensed context |
| `memory.lookup` | for `chat_history`: `searcher.search(...)` (semantic) — merged with compression summaries from SQLite when `session_ids` given; for `documents`: retrieval search hand-off over the same broker helper (project-RAG collection); for `user_profile_facts`: exact/keyword match over active facts (SQLite). Assemble per-source results + `sources`/`consulted` list |
| `memory.sources` | counts per source for the scope |
| `profile.read` | profile + active facts |
| `profile.update` | `supersede_fact` transaction, optional `basic_info_fields` reconcile, fire-and-forget index the new fact (kind='fact'), return fact + superseded + refreshed profile |

### 3.7 `domain_app.py`

Mirror `workflow_log_service/domain_app.py` with additions:

- `MemoryDomainServerContext`: handler, command consumer (`domain.memory.commands`,
  group `memory_service`), identity-event consumer (`identity.user.events`, group
  `memory_service.identity`), result-reply consumer for awaited retrieval
  replies (`helper.retrieval.results`, group `memory_service.retrieval`),
  producer.
- `create_domain_app(...)` wires the defaults; `create_default_domain_app`
  builds `SQLiteMemoryRepository`, `CondenseV1Policy`, and selects indexer /
  searcher / identity source by settings.
- `run_once` loop mirrors workflow_log; retrieval-reply consumption is a second
  loop feeding `BrokerMemorySearcher` pending futures.

### 3.8 `config.py`

`MemoryServiceSettings` (env-driven, mirror `WorkflowLogDomainSettings`):

```
MEMORY_SERVICE_NAME=memory_service
MEMORY_DOMAIN_COMMAND_TOPIC=domain.memory.commands
MEMORY_DOMAIN_RESULT_TOPIC=domain.memory.results
MEMORY_IDENTITY_TOPIC=identity.user.events
MEMORY_DB_PATH=/var/lib/rag/agent_memory.db
MEMORY_IDENTITY_MODE=broker | fake       # default broker; fake for standalone dev/tests
MEMORY_ALLOWED_SERVICES=conversation-server
MEMORY_INDEX_MODE=broker | fake          # fake indexes in-process for tests
MEMORY_SEARCH_MODE=broker | fake
SERVICE_AUTH_SIGNING_KEY / _TOKEN_ISSUER / _TOKEN_AUDIENCE  (shared with simple_agent local signing key)
```

### 3.9 `worker.py`

Mirror `workflow_log_service/worker.py` (health endpoint surface, `serve_forever`).

---

## 4. retrieval_service Memory-Indexing Integration

Retrieval service already owns the memory schemas
(`retrieval_service/memory/schemas/*`) and the Qdrant indexing/search machinery.

**Indexing hand-off (`memory_ingest`):**

- `RetrievalIndexHelperHandler` (`retrieval_service/indexing/domain_handler.py`)
  gains an `operation == "memory_ingest"` branch.
- New `RetrievalMemoryIndexCommand` in `retrieval_service/indexing/commands.py`
  that parses `chunks`/`payloads` as `MemoryChunk`/`MemoryChunkPayload`
  (reusing `retrieval_service/memory/schemas/documents.py`) and preserves the
  memory fields (`memory_id`, `owner_id`, `agent_id`, `memory_type`) in
  `to_qdrant_payload`.
- `IndexingService.index_chunks` is reused unchanged; the memory collection
  name is `"agent_memory"` (configurable). `MemoryChunkPayload.point_identity`
  yields deterministic Qdrant point IDs, so re-indexing the same memory is
  idempotent.
- `memory_service` publishes `helper.retrieval_index.commands` with
  `operation="memory_ingest"`, `attempt=1`, and does **not** await (async
  projection; SQLite is the source of truth — see §8 extensibility for the
  re-drive seam).

**Semantic search hand-off (`memory_search`):**

The document search path (`RetrievalService.search`) cannot be reused as-is:
it validates a `retrieval_filter` exposing `project_id`/`allowed_user_ids`
(`_validate_retrieval_filter`) and builds a Qdrant filter over `project_id`/
`user_id` keys, but memory points carry `owner_id`/`agent_id` (from
`MemoryChunkPayload.to_qdrant_payload`). The memory search is therefore a
**distinct, memory-aware path** that reuses the dense/sparse query machinery:

- `RetrievalHelperHandler` (`retrieval_service/server/domain_handler.py`) gains
  `operation == "memory_search"`, dispatched to
  `RetrievalHelperApiContext.handle_memory_search` →
  `RetrievalApiHandler.handle_memory_search`.
- New `MemorySearchCommand` in `retrieval_service/retrieval/contracts.py`
  carrying `project_id`, `user_id`, `agent_id`, `owner_id`, `query_text`,
  `collection_name`. Its `to_service_request()` produces a
  `RetrievalSearchRequest` (placeholder project/user ids) because the isolation
  filter is built separately.
- New `RetrievalService.search_memory(request, *, owner_id, agent_id)`
  (`retrieval_service/retrieval/service.py`): parses settings, builds the
  query via the existing `_build_query`, then **overrides the query filter** with
  a memory filter over `owner_id` (required) and `agent_id` (when given) using
  `_build_memory_filter`. Reuses `_search_candidates`/`_finalize_hits`/
  `_chunks_from_hits` unchanged.
- `MemorySearchCommand` is parsed from the broker payload by
  `RetrievalApiHandler.handle_memory_search`, which calls
  `app.search_memory(...)` and maps hits via `memory_search_result_to_mapping`
  to `{source_id, text, score, session_id, sequence_number, memory_id}` (the
  session/sequence fields ride in the memory payload metadata).
- `session_id`/`sequence_number` are carried into the Qdrant payload through the
  `MemoryChunkPayload.metadata` by `BrokerMemoryIndexer._record_metadata`
  (`memory_service/indexer.py`) and surfaced by the result mapper.

Both handlers reply on the existing `helper.retrieval_index.results` /
`helper.retrieval.results` topics keyed by `task_id` (existing pattern).

---

## 5. simple_agent Wiring

### 5.1 Memory client adapter (conversation-server)

New module:
`services/conversation-server/src/conversation_server/infrastructure/memory_client.py`

`MemoryClient(Protocol)` (application-facing interface):

```python
class MemoryClient(Protocol):
    async def record_session_start(self, *, actor, conversation_id, agent_id,
                                   request_id, traceparent) -> None: ...
    async def record_message(self, *, actor, message_id, conversation_id,
                             agent_id, role, sequence_number, content,
                             created_at, request_id, traceparent) -> None: ...
    async def record_session_close(self, *, actor, conversation_id,
                                   request_id, traceparent) -> None: ...
    async def compress(self, *, actor, conversation_id, start_sequence,
                       end_sequence, keep_recent, request_id,
                       traceparent) -> dict[str, Any]: ...
    async def lookup(self, *, actor, query, sources, request_id,
                     traceparent) -> dict[str, Any]: ...
    async def read_profile(self, *, actor, request_id, traceparent) -> dict[str, Any]: ...
    async def update_profile(self, *, actor, fact_type, subject, text,
                             source_message_id, request_id, traceparent) -> dict[str, Any]: ...
```

Two implementations:

- `MemoryBrokerClient` — production wiring. Uses `aiokafka` (already in
  requirements) to publish `DOMAIN_COMMAND` envelopes to
  `domain.memory.commands` (partition key `session_id`/`owner_user_id`) and
  consume `DOMAIN_RESULT` from `domain.memory.results`, matching on
  `correlation_id`. Mints a real service token via
  `simple_agent_service_auth.create_service_token` and sets the auth headers.
  Fire-and-forget methods publish without awaiting; `compress`/`lookup`/
  `read_profile`/`update_profile` await the correlated reply (with a timeout →
  `upstream_error`/503).
- `FakeMemoryClient` — local dev/tests. **Self-contained** deterministic
  in-process implementation of the `MemoryClient` Protocol (fixed fake
  sessions/messages/profile facts; deterministic compress/lookup/read/update
  responses matching the requirements payload shapes). It imports no RAG repo
  code and needs no broker, so the two repos stay independently testable. It
  mints a real service token over the same `create_service_token` code path
  (local signing key) so the auth path is exercised. Wired when
  `MEMORY_CLIENT_MODE=fake`.

Both share the exact same `MemoryClient` Protocol, so application code
(`provider_saga.py`) is transport-agnostic. (The RAG repo's own fake stack —
SQLite + fake indexer/searcher + `FakeIdentitySource` — covers AC-16 at the
handler level; the simple_agent `FakeMemoryClient` covers the saga level.)

### 5.2 Compression + lookup injection into the chat saga

File: `services/conversation-server/src/conversation_server/application/provider_saga.py`

1. `ConversationProviderSagaWorker.__init__` gains `memory_client:
   MemoryClient`.
2. In `execute_claim`, after `list_owned_messages`:
   - Fire-and-forget `memory_client.record_session_start(...)` (idempotent by
     `conversation_id`).
   - Fire-and-forget `memory_client.record_message(...)` for the user message
     (the run's `user_message_id` content from the messages list).
   - Fire-and-forget `memory_client.record_message(...)` for the assistant
     message on `provider.stream.completed` (content from `response_text`).
   - `record_session_close` fires on the conversation close path (when the
     conversation is marked closed), so FR-1.4 is wired end-to-end.
   - If `saga["context_snapshot"]` is absent, build it via a new
     `_build_snapshot_with_compression(...)` that:
     a. runs the existing `_context_snapshot` selection;
     b. if the selection truncated (older messages dropped) or
        `content_bytes >= 96_000`, calls `memory_client.compress(...)` over the
        dropped span (`start_sequence=1`, `end_sequence=first_selected-1`,
        `keep_recent=0`);
     c. prepends a synthetic **`{"role": "system", "content": condensed_context}`**
        message (a `system` role is provider-safe; a bare `"memory"` role would be
        rejected by strict LLM providers) and adds a synthetic `message_ref`
        `{message_id: memory_id, role: "memory", sequence_number: 0}` (the
        `"memory"` role is an internal marker only, not sent to the provider);
     d. bumps `policy_version` to `context-v2` and records
        `compressed: {memory_id, covered_from, covered_to}`.
   - Optional (config `MEMORY_INJECT_PROFILE`): on the first run of a
     conversation, `memory_client.read_profile(...)` and append active facts as
     a system block when non-empty.
3. The provider `body["messages"]` is the snapshot `messages` (now possibly
   containing the synthetic memory message).

This keeps the compression contract span-based and idempotent (FR-2.6): the
saga compresses a fixed dropped span; re-running a claim re-derives the same
span and memory_service dedups by deterministic `memory_id`.

### 5.3 identity-server event publish

File: `services/identity-server/src/identity_server/infrastructure/sqlite_identity_repository.py`

- `_enqueue_identity_event` gains `email` and `display_name` parameters and
  adds them to the payload (`event_version` stays `1`; the fields are additive
  optional). `create_registered_user` and `save_user` callers pass
  `profile.email` / `profile.display_name`.

New module:
`services/identity-server/src/identity_server/infrastructure/redpanda_identity_publisher.py`

- `RedpandaIdentityEventPublisher(IdentityEventPublisher)` publishes each
  outbox event to `identity.user.events` with key `user_id`, topic per C2.
- `worker.py`: compose a `FanOutIdentityEventPublisher` wrapping the existing
  HTTP usage publisher and the new Redpanda publisher; the outbox row is marked
  published when both succeed (Redpanda failure keeps the row pending/retrying,
  matching the existing outbox retry semantics).

Note: `contracts/events/*` and `contracts/openapi/identity-server.yaml` gain a
reference schema for `identity.user.registered` documenting the payload
(single source of truth: the outbox payload + `email`/`display_name`).

### 5.4 Config and wiring

- `configs/conversation-server/{local,dev,production}.yaml`: add a `memory`
  block (`client_mode: fake|broker`, `bootstrap_servers_env:
  REDPANDA_BOOTSTRAP_SERVERS`, command/result topic names, `inject_profile`).
- `services/conversation-server/src/conversation_server/main.py` and
  `worker.py`: build the `MemoryClient` (broker or fake per config) and pass it
  to `ConversationProviderSagaWorker`.
- `contracts/openapi/conversation-server.yaml`: document the memory client
  config and the saga `context-v2` snapshot shape (informational).

---

## 6. Data Flow Diagrams (ASCII)

### 6.1 Session start + message recording (async, fire-and-forget)

```
conversation-server                          memory_service                          retrieval_service
      | record_session_start / record_message (DOMAIN_COMMAND, key=session_id)          |
      |  --publish, no await---> domain.memory.commands ---consume--> MemoryDomainHandler|
      |                                                                                  |
      |                               upsert session / insert message (SQLite, tx + idempotency)
      |                               index hand-off: HELPER_COMMAND operation=memory_ingest
      |                                             ---publish (no await)--> helper.retrieval_index.commands
      |                                                                     ---consume--> RetrievalIndexHelperHandler
      |                                                                                    embed + upsert Qdrant
      |                                                                                    HELPER_RESULT -> helper.retrieval_index.results (observed, not awaited)
      |                              DOMAIN_RESULT -> domain.memory.results (observability)
```

### 6.2 Compression (request/reply)

```
conversation-server                          memory_service                          retrieval_service
      | memory.compress (DOMAIN_COMMAND, key=session_id, corr=C)                         |
      |  --publish + await reply--> domain.memory.commands ---consume--> handler          |
      |                                          load span messages from SQLite            |
      |                                          CondenseV1Policy.compress(span)            |
      |                                          memory_id = mem_sum_<sha256(span)>         |
      |                                          persist MemoryRecord (dedup by memory_id)  |
      |                                          index hand-off (memory_ingest, no await) -->
      |                                          DOMAIN_RESULT (corr=C, key=task_id)        |
      |  <--match corr=C-- domain.memory.results <--publish                                |
      |  prepend {"role":"memory", "content": condensed} to context snapshot
```

### 6.3 Cross-source lookup (request/reply)

```
conversation-server                          memory_service                          retrieval_service
      | memory.lookup (DOMAIN_COMMAND, corr=L)                                             |
      |  --publish + await--> domain.memory.commands ---consume--> handler                 |
      |                             chat_history:   HELPER_COMMAND op=memory_search
      |                                           ---publish + await reply--> helper.retrieval.commands
      |                                                                     ---consume--> RetrievalHelperHandler
      |                                                                                    Qdrant search (MemoryQueryScope)
      |                                           <--HELPER_RESULT (corr match)-- helper.retrieval.results
      |                             documents:      same helper search (project-RAG collection)
      |                             user_profile_facts: SQLite exact/keyword over active facts
      |                             assemble per-source results + sources/consulted list
      |                             DOMAIN_RESULT (corr=L) -> domain.memory.results
      |  <--match corr=L-- (response)
```

### 6.4 Profile init/update

```
identity-server                              memory_service
      | user registered/status_changed -> identity.user.events (key=user_id)              |
      |  --publish--> identity.user.events ---consume (group memory_service.identity)-->   |
      |                          BrokerIdentitySource.on_user_registered/on_user_status_changed
      |                          upsert user_profiles.basic_info (identity_revision, tx)

conversation-server                          memory_service
      | profile.update (DOMAIN_COMMAND, corr=U)                                            |
      |  --publish + await--> domain.memory.commands ---consume--> handler                 |
      |                          supersede_fact tx (mark inactive, insert active v+1)
      |                          reconcile basic_info_fields vs account data
      |                          index hand-off (kind='fact', no await)
      |                          DOMAIN_RESULT (corr=U) -> domain.memory.results
      |  <--match corr=U-- (fact + superseded + refreshed profile)
```

---

## 7. Build Order / Task Breakdown

The developers implement in this order (each step is independently testable):

1. **Shared contracts** — C1 (`data_types.py` executable flag), C2
   (`topics.py` identity topic), C3 (`shared/service_auth.py`). Tests:
   `tests/test_shared_contracts.py` additions.
2. **memory_service core** — `models.py`, `repository.py` (in-memory +
   SQLite + DDL), `compression.py` (`CondenseV1Policy`), `identity.py`
   (`FakeIdentitySource`). Unit tests with in-memory repo (AC-1..4, AC-9..12,
   AC-13).
3. **memory_service domain handler** — `domain_handler.py` with fake
   indexer/searcher/identity; `domain_app.py`/`worker.py`/`config.py`.
   Unit tests for all 8 operations (AC-1..15) using `FakeProducer` +
   in-memory repo + fakes (mirror `tests/workflow_log/test_domain_handler.py`).
4. **retrieval_service hand-off** — `memory_ingest` on the index helper,
   `memory_search` on the retrieval helper, memory collection config.
   Unit tests in `tests/retrieval/`.
5. **memory_service ↔ retrieval integration** — a broker-wired integration
   test (`tests/integration/`) covering compress→index→lookup round trip and
   `memory_id` dedup (AC-5, AC-6, AC-7).
6. **identity event path** — `BrokerIdentitySource`; identity-server
   publisher + payload extension (AC-9 via broker).
7. **simple_agent memory client** — `MemoryClient` Protocol,
   `FakeMemoryClient`, `MemoryBrokerClient`; config + wiring in
   `main.py`/`worker.py`.
8. **saga integration** — compression + message-recording hooks in
   `provider_saga.py` (`_build_snapshot_with_compression`, record calls,
   profile injection). Unit tests in simple_agent with `FakeMemoryClient`.
9. **End-to-end** — full local runtime with a real broker (Redpanda) and real
   wiring: chat → record → compress at limit → lookup → profile.
10. **Docs** — update `docs/README.md` link text from DRAFT to approved;
    reference the two docs.

---

## 8. Test Plan

| Layer | What | Fakes (same code paths) |
| --- | --- | --- |
| Unit — memory_service | Repository (SQLite on `:memory:` and in-memory), `CondenseV1Policy` determinism, `domain_handler` 8 operations, idempotency, error mapping, scope enforcement | `FakeProducer`, in-memory repo, `FakeMemoryIndexer`, `FakeMemorySearcher`, `FakeIdentitySource` |
| Unit — retrieval_service | `memory_ingest`/`memory_search` command parsing + handler branches | existing fake Qdrant/embedding fixtures |
| Integration — RAG repo | Compress→index→lookup round trip over a real (test) broker; `memory_id` dedup; profile event consumption | SQLite repo + real `CondenseV1Policy`; broker test harness from `tests/integration/` |
| Unit — simple_agent | `provider_saga` compression injection and record hooks; `MemoryBrokerClient` envelope/correlation behavior | `FakeMemoryClient`, in-memory conversation repo |
| Integration — simple_agent | conversation-server ↔ fake memory service over the `MemoryClient` Protocol | `FakeMemoryClient` backed by the RAG test harness domain handler |
| End-to-end | Local stack with Redpanda: chat → record → compress at 96k/128 limit → lookup → profile update → profile read | real wiring only |

Deterministic fake data: `FakeIdentitySource` seeds fixed users; fake
lookup/index results are deterministic; all assertions compare exact values.
AC-16 (full suite without broker) must pass with `MEMORY_IDENTITY_MODE=fake`,
`MEMORY_INDEX_MODE=fake`, `MEMORY_SEARCH_MODE=fake`.

---

## 9. Extensibility Seams

| Seam | Today | Swap-in |
| --- | --- | --- |
| Compression method (FR-2.5) | `CondenseV1Policy` | `ModelSummaryPolicy` behind `CompressionPolicy`; new `policy` string, same contract |
| Lookup sources | 3 sources (`chat_history`, `documents`, `user_profile_facts`) | add a source id → its resolver in the lookup assembly; response shape already keyed per source |
| Fact types | open string (`fact_type`) | no schema change; type-specific validation may be added per type |
| Identity enrichment | `BrokerIdentitySource` (events) + `FakeIdentitySource` | `DirectReadIdentitySource` for backfill; agent-ownership cross-check |
| Index durability | async best-effort projection (SQLite is source of truth) | periodic re-index job scanning `memory_records` lacking a Qdrant point; index status column |
| Retention/TTL (OQ-3 follow-up) | none | scheduled compaction job over `messages`/`memory_records` |
| Replay operation (FR-1.3 follow-up) | conversation-server serves live replay | `history.replay` domain operation paging `messages` |
| Transport | Redpanda request/reply | swap `BrokerMemoryIndexer`/`BrokerMemorySearcher`/`MemoryBrokerClient` behind their Protocols |
| Agent-ownership defense | caller-enforced | `AgentOwnershipVerifier` adapter inside memory_service |

---

## 10. Reference Files

Mirror of requirements §12, plus the files this design adds or changes:

RAG service (this repo):

- `shared/contracts/data_types.py`, `shared/contracts/topics.py`,
  `shared/service_auth.py` (new)
- `memory_service/` (new package, §3)
- `retrieval_service/indexing/domain_handler.py`,
  `retrieval_service/indexing/commands.py`,
  `retrieval_service/server/domain_handler.py`,
  `retrieval_service/retrieval/contracts.py`
- `tests/memory/` (new), `tests/retrieval/`, `tests/integration/`

Simple Agent repo:

- `services/conversation-server/src/conversation_server/infrastructure/memory_client.py` (new)
- `services/conversation-server/src/conversation_server/application/provider_saga.py`
- `services/conversation-server/src/conversation_server/main.py`, `worker.py`
- `services/identity-server/src/identity_server/infrastructure/redpanda_identity_publisher.py` (new)
- `services/identity-server/src/identity_server/infrastructure/sqlite_identity_repository.py`
- `services/identity-server/src/identity_server/worker.py`
- `configs/conversation-server/*.yaml`, `contracts/openapi/conversation-server.yaml`
