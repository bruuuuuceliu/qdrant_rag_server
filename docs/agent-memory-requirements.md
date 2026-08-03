# Agent Memory, Chat History, and User Profile — Requirements

Status: **Approved for implementation** — locked spec; the team implements
strictly from this document and the companion design doc
(`docs/agent-memory-design.md`). No open questions remain; decisions are locked
in §11.
Date: 2026-08-02
Owner: this repository (the RAG service)
Version: 1.0

> **Supersedes** the earlier "Simple Agent Integration" design draft and the
> prior DRAFT version of this document. The projects are now **one project**,
> and this document states the requirements the RAG service must satisfy as the
> durable memory/knowledge layer for the chat platform.

---

## 1. Overview

The RAG service is no longer only a document-retrieval engine. It becomes the
**durable memory and knowledge layer** for the chat platform. In addition to
document RAG, the service must:

1. **Record every chat session and every message** so chat history is
   searchable and reusable.
2. **Compress chat history on demand** when the agent's context window is
   exhausted, returning a condensed context and persisting it as memory.
3. **Answer queries across three sources** — chat history, documents, and user
   profile/facts — returning a list of the sources used for each query.
4. **Maintain a user profile** with basic user info and a versioned **facts**
   section that updates (not just inserts) as the user chats.

Because this project and the Simple Agent project are **one project**, the RAG
service may also read Simple Agent-owned data directly — such as the user's key
(identifier), registration email, and name — to initialize and enrich user
profiles. The primary profile-initialization path is event-driven (see FR-4.2);
direct reads are an explicitly permitted fallback.

The retrieval core stays; the four requirements above are additive capabilities
built on the same ingest/search pipeline.

---

## 2. Scope and Context

### 2.1 One project

- This repository and Simple Agent form a single project.
- Cross-querying Simple Agent data is **welcomed and expected**, not a boundary
  violation: user key (`user_id`), registration email, display name, roles, and
  other account basics may be read to build profiles and enrich memory.
- Local integration no longer requires "two separate stacks"; the RAG service
  runs as part of the one project.

### 2.2 What stays the same

- Broker-first service topology and the manager gRPC edge remain the external
  surface. The manager gRPC edge is **not** extended for the agent service; it
  remains the browser/SDK surface.
- Document RAG (ingest → chunk → embed → index → search) remains the core.
- Owner/agent scoping continues to be enforced on every lookup.

### 2.3 What is new

- Chat-session and message persistence (a first-class data type).
- On-demand chat-history compression.
- Multi-source retrieval with an explicit per-query source list.
- User profile + versioned facts with update (not insert-only) semantics.

### 2.4 Out of scope for this iteration

- Model-backed summarization (deterministic v1 only; see OQ-2).
- Passive fact extraction from message content (explicit profile-update
  requests only; see OQ-4).
- Retention/TTL for raw messages (raw messages are kept indefinitely; see
  OQ-3).
- A dedicated `history.replay` domain operation (within-session ordered replay
  is served by conversation-server's own message store; a replay operation over
  memory_service's store is a declared follow-up).
- A manager gRPC route for `agent_memory` (out of scope by steering; the
  agent-service caller publishes broker domain commands directly).

---

## 3. Terminology

| Term | Meaning |
| --- | --- |
| **Chat session** | One conversation between a user and an agent (Simple Agent `conversation_id`). |
| **Message** | A single user or assistant turn within a session. |
| **Session classifier / identifier** | The metadata record the RAG service creates for a new session (session ID, owner, agent, timestamps, status) that tags every message. |
| **Chat history** | The ordered sequence of messages in one or more sessions, recorded in the RAG service. |
| **Memory** | Durable knowledge derived from chat: recorded messages, compressed summaries, and extracted facts. |
| **Compression / condensed context** | A shorter representation of a chat-history span produced by the RAG service when context limits are reached. |
| **Source** | One of the three retrieval domains: `chat_history`, `documents`, `user_profile_facts`. |
| **User profile** | Per-user record with **basic info** (from account data) and a **facts** section. |
| **Fact** | A discrete, versioned claim about the user (e.g. "prefers email", "born 1990-05-12"). |
| **Active / inactive fact** | Versioned lifecycle: a superseded fact is marked **inactive**; the replacement is inserted as **active**. |
| **DOMAIN_COMMAND** | The `MessageType.DOMAIN_COMMAND` broker envelope that carries a memory operation request. |
| **DOMAIN_RESULT** | The `MessageType.DOMAIN_RESULT` broker envelope that carries the operation result (or error). |
| **Verified service identity** | The identity in the caller's signed service token (service name + actor `user_id` + role), verified by memory_service against the shared HS256 signing key. |

---

## 4. Functional Requirements

### FR-1 — Chat session recording

**FR-1.1 Session start.** When the user starts a new chat session, the agent
service notifies the RAG service, which creates a **session classifier /
identifier** — a metadata record — for it. The record includes at minimum:

- `session_id` (maps to Simple Agent `conversation_id`)
- `owner_user_id` (maps to Simple Agent `user_id`, from verified identity)
- `agent_id`
- `started_at`, `status` (`active` | `closed`)
- optional `metadata` (title, entry point, tags)

**FR-1.2 Message recording.** Every message in the session — user and assistant —
is recorded by the RAG service and durably indexed. Each message carries:

- `message_id`, `session_id`
- `role` (`user` | `assistant`), `sequence_number`
- `content` (full text), `created_at`
- `agent_id`, `owner_user_id` (for scoping)
- optional `metadata` (web_search used, attachments, tool calls)

**FR-1.3 Retrievability.** Recorded messages are:
- retrievable in order **within a session** (history replay), served by
  conversation-server's own message store for the live conversation and by
  memory_service's durable copy as the backup; a dedicated replay operation is
  a declared follow-up.
- searchable **across sessions** for the same owner/agent (semantic lookup over
  chat history via the retrieval index hand-off).

**FR-1.4 Session close.** The agent may mark a session `closed`; the RAG service
records the close time. Closed sessions remain searchable.

**FR-1.5 Durability.** Message recording is durable and, where practical,
asynchronous so chat latency is unaffected; ordering per session is preserved
(broker partitioning by `session_id`).

---

### FR-2 — Context compression

**FR-2.1 Trigger.** When the agent's context window reaches its limit, the agent
service sends a compression request to the RAG service.

**FR-2.2 Input.** The request identifies the span to compress:
- a `session_id` plus a `start_sequence`/`end_sequence` boundary (compress
  history between message sequences), or
- an explicit list of messages/history passed in the request (v1 accepts the
  span form only; the explicit-message form is a follow-up).

**FR-2.3 Output.** The RAG service compresses the span and returns a
**condensed context** to the agent service (a shorter text that preserves key
facts, decisions, and user preferences from the span).

**FR-2.4 Persistence.** The condensed context is **persisted as memory**, tagged
with the session, agent, owner, and the message span it covers, so future
lookups can surface it (it becomes part of `chat_history`-class memory).

**FR-2.5 Compression method.** v1 uses the deterministic `condense-v1` policy
(locked in OQ-2). The method is swappable behind the stable FR-2 contract
(condensed context in, condensed context out + persisted record).

**FR-2.6 Idempotency.** Compressing the same span twice with the same inputs
produces equivalent condensed context with the **same deterministic `memory_id`**
(same record key) rather than duplicate memory. See §9.

---

### FR-3 — Cross-source retrieval and question answering

**FR-3.1 Query.** The agent may send a query (a question or a search) to the RAG
service. The service performs retrieval **across three sources**:

| Source | Content |
| --- | --- |
| `chat_history` | Recorded messages + compressed summaries for the owner/agent (vector index + SQLite). |
| `documents` | RAG collections attached to the agent (existing document RAG). |
| `user_profile_facts` | Active facts from the user profile (exact/keyword match over facts). |

**FR-3.2 Per-source results.** The response contains, **for each source**,
the retrieved items: `text`, `score`, `source` (type), and a stable `source_id`
(e.g. `message_id`, `doc_id`/`chunk_id`, `fact_id`).

**FR-3.3 Source list.** The response includes a **list of the sources that were
required/used for the query**, plus the matched items under each. If a source
produced no matches, it is still reported as consulted (so the agent knows what
was and was not searched).

**FR-3.4 Scope enforcement.** All lookups are bounded by `owner_user_id` and
`agent_id` derived from the caller's verified identity — never from
client-supplied owner IDs. See §8.

**FR-3.5 Optional merge.** The service may also return a merged, ranked list;
the per-source structure is always present (the source list is the primary
contract).

**FR-3.6 Answerability.** The response is retrieval output (context), not
generated prose. Answer synthesis stays with the agent's LLM/provider layer.

---

### FR-4 — User profile and facts

**FR-4.1 Profile ownership.** The RAG service maintains exactly one profile per
user (`user_id`).

**FR-4.2 Basic info.** The profile contains basic user info: user key
(`user_id`), registration email, display name, role, and account status. This
section is **initialized and refreshed from Simple Agent identity data**. The
primary mechanism is **event-driven**: memory_service consumes identity user
events (`identity.user.registered`, `identity.user.status_changed` — the
`event_type` carries no `.v1` suffix; versioning is the separate
`event_version: 1` field) to upsert `user_profiles.basic_info`. A deterministic **fake identity adapter** is
used for local dev and tests so memory_service runs standalone. Direct reads of
identity tables are permitted (§5) and are the documented backfill/bootstrap
tool, not the primary path. The agent may not invent basic info; account data is
authoritative.

**FR-4.3 Facts section.** The profile contains a facts section recording known
facts about the user (e.g. eating habits, date of birth, preferences). Each fact
is a discrete record.

**FR-4.4 Profile update requests.** As the user chats, the agent may send
profile update requests to the RAG service. The service applies them.

**FR-4.5 Update semantics — not insert-only.** A profile update may
**replace** existing information, not just append:
1. **Find** the existing active fact(s) for the same `(user_id, fact_type,
   subject)`.
2. **Mark existing** records **inactive** (with `superseded_by` pointing to the
   replacement).
3. **Insert** the new record as **active**.

Rules:
- At most one **active** fact per `(user_id, fact_type, subject)` — enforced by
  a unique partial index (see §6) **and** application logic (index errors are
  treated as races, not silent drops).
- Inactive facts are retained (auditable history, removable) but never returned
  as current.
- A fact is uniquely addressable: `fact_id` + `version`.

**FR-4.6 Basic info updates.** Updates to basic info reconcile against account
data; only fields explicitly updated by the profile-update request may change,
and conflicting account data takes precedence (account data is authoritative).

**FR-4.7 Attribution and audit.** Every profile/fact change records `updated_by`
(`agent_id` or `system`), `source_message_id` when the fact came from a chat
message, `created_at`, `updated_at`. Changes are auditable.

**FR-4.8 Read API.** The agent can read the current profile (basic info +
**active** facts) to inject into chat context.

---

## 5. Cross-project Data Access (one project)

Because this project and Simple Agent are one project, the RAG service:

- **May read** Simple Agent identity data directly: `user_id`, registration
  email, display name, role, account status, agent configs.
- **Uses** that data to initialize `user_profile.basic_info` and to resolve
  identity when recording sessions/messages.
- **Must not** silently write Simple Agent-owned tables outside its own
  ownership boundary; writes to identity/agent data still go through the owning
  service, but **reads** for profile/memory enrichment are permitted in-process.

**Decision:** events are the primary profile-enrichment path (FR-4.2); direct
cross-DB reads are permitted for backfill/bootstrap only. Rationale: events
decouple lifecycle, survive restarts via replay, and keep memory_service
standalone-testable with a fake identity source.

---

## 6. Storage Schema (memory_service SQLite store)

The memory_service owns a SQLite database (default
`/var/lib/rag/agent_memory.db`; env `MEMORY_DB_PATH`). DDL-level contract:

```sql
-- Sessions: one row per chat session (FR-1.1)
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    owner_user_id     TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    started_at        TEXT NOT NULL,          -- ISO-8601 UTC
    closed_at         TEXT,
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_owner_agent
    ON sessions(owner_user_id, agent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_owner_status
    ON sessions(owner_user_id, status);

-- Messages: one row per recorded turn (FR-1.2)
CREATE TABLE IF NOT EXISTS messages (
    message_id        TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL REFERENCES sessions(session_id),
    owner_user_id     TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    role              TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    sequence_number   INTEGER NOT NULL CHECK (sequence_number >= 1),
    content           TEXT NOT NULL,
    created_at        TEXT NOT NULL,          -- ISO-8601 UTC
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    UNIQUE (session_id, sequence_number)
);
CREATE INDEX IF NOT EXISTS idx_messages_owner_agent
    ON messages(owner_user_id, agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session_order
    ON messages(session_id, sequence_number);

-- Memory records: messages (kind='message'), compressed summaries
-- (kind='compression_summary'), and facts mirrored for semantic lookup
-- (kind='fact'). Vector indexing is a projection of this table via
-- retrieval_service; SQLite remains the source of truth.
CREATE TABLE IF NOT EXISTS memory_records (
    memory_id         TEXT PRIMARY KEY,
    session_id        TEXT,
    owner_user_id     TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('message', 'compression_summary', 'fact')),
    content           TEXT NOT NULL,
    covered_from      INTEGER,                -- compression span, inclusive
    covered_to        INTEGER,                -- compression span, inclusive
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_owner_agent
    ON memory_records(owner_user_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_session_span
    ON memory_records(session_id, covered_from, covered_to);

-- User profiles: exactly one per user (FR-4.1)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id           TEXT PRIMARY KEY,
    basic_info_json   TEXT NOT NULL DEFAULT '{}',   -- email, display_name, role, account_status
    identity_revision INTEGER NOT NULL DEFAULT 0,   -- last applied identity event revision
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

-- User facts: versioned, superseding (FR-4.5)
CREATE TABLE IF NOT EXISTS user_facts (
    fact_id           TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL REFERENCES user_profiles(user_id),
    fact_type         TEXT NOT NULL,
    subject           TEXT NOT NULL DEFAULT '',
    text              TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
    version           INTEGER NOT NULL CHECK (version >= 1),
    superseded_by     TEXT,                    -- fact_id of the replacement, NULL when active
    updated_by        TEXT NOT NULL,           -- agent_id or 'system'
    source_message_id TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
-- Unique partial index: exactly one ACTIVE fact per (user_id, fact_type, subject)
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_facts_one_active
    ON user_facts(user_id, fact_type, subject)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_user_facts_user_type_version
    ON user_facts(user_id, fact_type, version);

-- Idempotency: mutation replay table (see §9)
CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key   TEXT PRIMARY KEY,
    operation         TEXT NOT NULL,
    request_hash      TEXT NOT NULL,
    result_json       TEXT NOT NULL,
    created_at        TEXT NOT NULL
);
```

### Versioning / supersession rules (FR-4.5)

- On `profile.update` for `(user_id, fact_type, subject)`:
  1. In one transaction, `SELECT ... WHERE user_id=? AND fact_type=? AND
     subject=? AND status='active' FOR UPDATE`.
  2. Mark each found row `status='inactive'`, `superseded_by=<new fact_id>`,
     `updated_at=now`.
  3. Insert the new row with `version = (max(version) over the same key) + 1`,
     `status='active'`.
  4. `updated_by` = caller's `agent_id` (or `system` for identity/backfill
     writes). `source_message_id` recorded when present.
- Inactive facts are never returned as current and never collide on the unique
  partial index. A unique-index violation on insert is treated as a concurrent
  supersession race: the transaction aborts and returns `conflict` (409); the
  caller may retry with a fresh read.

### Sequence ordering for messages (FR-1.5)

- `sequence_number` is assigned by conversation-server (per-session order) and
  carried in `message.record`. memory_service persists it as-is and enforces
  `UNIQUE (session_id, sequence_number)`. Duplicates are deduped (replayed),
  never re-inserted.
- Broker partitioning guarantees per-session arrival order: the publishing key
  for session-scoped commands is `session_id` (see §7 envelope rules).

---

## 7. Broker Transport Contract (authoritative)

Memory interactions go over Redpanda request/reply on the reserved
`domain.memory.commands` / `domain.memory.results` topics. The manager gRPC
edge is **not** extended.

### 7.1 Envelope rules (all operations)

| Field | Value / rule |
| --- | --- |
| `message_type` | `domain.command` (`MessageType.DOMAIN_COMMAND`) on request; `domain.result` (`MessageType.DOMAIN_RESULT`) on reply |
| `data_type` | `agent_memory` (str of `DataType.AGENT_MEMORY`) |
| `schema_version` | `1` |
| `producer` (request) | caller service name, e.g. `conversation-server` |
| `producer` (reply) | `memory_service` |
| `correlation_id` | caller-generated; **echoed verbatim** in the reply; the caller matches replies by `correlation_id` + `operation` |
| `task_id` | caller-generated; used as the reply publish key |
| `headers` (request, auth) | `X-Service-Name`, `Authorization: Bearer <service-token>`, `X-Actor-User-ID`, `X-Actor-Role`, `X-Agent-ID`, `traceparent` (see §8). Local/fake mode mints a real token with the local signing key over the same code path. |
| `payload` (request) | `{operation, request: {...}, context: {...}, source_message_id: "..."}` (the `DomainCommandPayload` shape) |
| `payload` (reply) | `{operation, result: {...}, attempt, retryable, error, source_message_id}` (the `DomainResultPayload` shape) |
| **Publish key (partitioning)** | session-scoped ops (`session.start`, `message.record`, `session.close`, `memory.compress`) → `session_id`; user-scoped ops (`memory.lookup`, `memory.sources`, `profile.read`, `profile.update`) → `owner_user_id`. This preserves per-session/per-user ordering. |
| **Response topic** | default `domain.memory.results` (derived from `data_type`). The caller MAY set `context.response_topic` to override for merged deployments. Reply key = `task_id`. |
| **Consumed topic** | `domain.memory.commands` (consumer group `memory_service`) |

**Fire-and-forget vs request/reply:**

| Operations | Mode | Why |
| --- | --- | --- |
| `session.start`, `message.record`, `session.close` | **Fire-and-forget** — caller publishes and does not await; broker durability + SQLite are the guarantee (FR-1.5) | Chat latency unaffected; caller already holds the data locally |
| `memory.compress`, `memory.lookup`, `memory.sources`, `profile.read`, `profile.update` | **Request/reply** — caller publishes and awaits the DOMAIN_RESULT matching its `correlation_id` | The caller needs the answer before responding / before injecting context |

memory_service publishes a DOMAIN_RESULT for **every** command (including
fire-and-forget ops) for observability and testability; fire-and-forget simply
means the caller does not block on it.

### 7.2 Operations

All `request` field tables list name, type, and optionality. `owner_user_id` is
**never** a request field (derived from verified identity, §8).

`agent_id` appears in the payload only for **agent-scoped** operations —
`session.start`, `message.record`, `memory.compress` — where it is required and
cross-checked against the `X-Agent-ID` header. The remaining operations
(`session.close`, `memory.lookup`, `memory.sources`, `profile.read`,
`profile.update`) are **user-scoped**: the `X-Agent-ID` header is still sent by
the caller (the agent the user is chatting with, used for scoping facts) but is
**not** compared against a payload field. The caller's service token always
carries `actor_user_id`, which becomes `owner_user_id` for the whole request.

#### 7.2.1 `session.start` (FR-1.1) — fire-and-forget

Request fields:

| Field | Type | Optional | Notes |
| --- | --- | --- | --- |
| `session_id` | string | required | maps to Simple Agent `conversation_id` |
| `agent_id` | string | required | must equal `X-Agent-ID` header |
| `started_at` | string | optional | ISO-8601 UTC; defaults to now |
| `metadata` | object | optional | title, entry_point, tags |
| `idempotency_key` | string | optional | default `session:{session_id}` |

Result (`result`):
```jsonc
{
  "session": {
    "session_id": "con_...", "owner_user_id": "user_1", "agent_id": "agent_1",
    "status": "active", "started_at": "2026-08-02T10:00:00Z",
    "metadata": {}, "created_at": "...", "updated_at": "..."
  },
  "created": true,          // false when the session already existed (replay)
  "replayed": false
}
```

#### 7.2.2 `message.record` (FR-1.2) — fire-and-forget

Request fields:

| Field | Type | Optional | Notes |
| --- | --- | --- | --- |
| `message_id` | string | required | |
| `session_id` | string | required | |
| `agent_id` | string | required | |
| `role` | string | required | `user` \| `assistant` |
| `sequence_number` | integer | required | >= 1, per-session |
| `content` | string | required | full text |
| `created_at` | string | optional | ISO-8601 UTC |
| `metadata` | object | optional | web_search, attachments, tool_calls |
| `idempotency_key` | string | optional | default `message:{message_id}` |

Result:
```jsonc
{
  "message": {
    "message_id": "msg_...", "session_id": "con_...", "owner_user_id": "user_1",
    "agent_id": "agent_1", "role": "user", "sequence_number": 4,
    "content": "...", "created_at": "...", "metadata": {}
  },
  "recorded": true,     // false when message_id already existed (dedup)
  "indexed": true       // true when the vector-index hand-off was queued successfully; false when it was skipped/failed. Since the hand-off is fire-and-forget, this reflects "queued", not eventual index success.
}
```

#### 7.2.3 `session.close` (FR-1.4) — fire-and-forget

Request fields:

| Field | Type | Optional | Notes |
| --- | --- | --- | --- |
| `session_id` | string | required | |
| `closed_at` | string | optional | ISO-8601 UTC; defaults to now |
| `idempotency_key` | string | optional | default `session.close:{session_id}` |

Result:
```jsonc
{
  "session": { "session_id": "con_...", "status": "closed", "closed_at": "..." },
  "changed": true        // false when already closed
}
```

#### 7.2.4 `memory.compress` (FR-2) — request/reply

Request fields:

| Field | Type | Optional | Notes |
| --- | --- | --- | --- |
| `session_id` | string | required | |
| `start_sequence` | integer | optional | default `1`; inclusive lower bound |
| `end_sequence` | integer | required | inclusive upper bound |
| `keep_recent` | integer | optional | default `0`; number of newest messages in the span kept verbatim (uncondensed) and returned separately |
| `policy` | string | optional | default `condense-v1` |
| `idempotency_key` | string | optional | default `compress:{session_id}:{start_sequence}:{end_sequence}:{keep_recent}:{policy}` |

Result (authoritative payload schema; the draft shape is kept and made exact):
```jsonc
{
  "condensed_context": "User discussed refund policy; prefers email contact...",
  "memory_id": "mem_sum_<sha256(span)[:24]>",
  "covered_range": { "from": 1, "to": 40 },
  "policy": "condense-v1",
  "replayed": false,        // true when a summary for this span already existed
  "recent_messages": [      // only when keep_recent > 0
    { "message_id": "...", "sequence_number": 36, "role": "user", "content": "..." }
  ]
}
```
`covered_range` is `{from: start_sequence, to: end_sequence}` after applying
`keep_recent` (i.e., `to = end_sequence - keep_recent`). The persisted summary
covers exactly `[from, to]`.

#### 7.2.5 `memory.lookup` (FR-3) — request/reply

Request fields:

| Field | Type | Optional | Notes |
| --- | --- | --- | --- |
| `query` | string | required | |
| `sources` | list\<string\> | optional | subset of `["chat_history", "documents", "user_profile_facts"]`; default all three |
| `collection_name` | string | optional | for the `documents` source: the project-RAG collection to search; default `agent_memory` (memory_service config `MEMORY_DOCUMENTS_COLLECTION`). The agent→collection mapping is resolved by the caller (conversation-server knows the agent's attached RAG collection); v1 uses a single configured collection. |
| `top_k` | integer | optional | default 5, per source |
| `session_ids` | list\<string\> | optional | restrict `chat_history` to these sessions |
| `include_shared` | bool | optional | default false |

Result (authoritative; the draft lookup shape is preserved exactly and made
precise):
```jsonc
{
  "query": "what are the user's dietary restrictions?",
  "sources": ["user_profile_facts", "chat_history", "documents"],   // consulted, in order
  "consulted": { "chat_history": true, "documents": true, "user_profile_facts": true },
  "results": {
    "chat_history": [
      { "source": "chat_history", "source_id": "msg_...",
        "text": "The user mentioned avoiding gluten...", "score": 0.81,
        "session_id": "con_...", "sequence_number": 12 }
    ],
    "documents": [],
    "user_profile_facts": [
      { "source": "user_profile_facts", "source_id": "fact_...",
        "text": "dietary: avoids gluten", "score": 0.95 }
    ]
  },
  "merged": [  // optional ranked merge (FR-3.5); present when enabled by config
    { "source": "user_profile_facts", "source_id": "fact_...", "score": 0.95 }
  ],
  "elapsed_ms": 42
}
```
Every requested source appears in `sources` and `consulted` even with zero
matches (FR-3.3).

#### 7.2.6 `memory.sources` (FR-3.3) — request/reply

Request fields: none (scope comes from verified identity). Optional `sources`
filter list.

Result:
```jsonc
{
  "scope": { "owner_user_id": "user_1", "agent_id": "agent_1" },
  "sources": [
    { "source": "chat_history", "available": true,  "count": 128 },
    { "source": "documents",    "available": false, "count": 0 },
    { "source": "user_profile_facts", "available": true, "count": 3 }
  ]
}
```

#### 7.2.7 `profile.read` (FR-4.8) — request/reply

Request fields:

| Field | Type | Optional | Notes |
| --- | --- | --- | --- |
| `include_inactive_facts` | bool | optional | default false |

Result:
```jsonc
{
  "profile": {
    "user_id": "user_1",
    "basic_info": { "email": "a@b.c", "display_name": "A", "role": "tier_1", "account_status": "active" },
    "active_facts": [
      { "fact_id": "fact_...", "fact_type": "dietary", "subject": "", "text": "avoids gluten",
        "version": 2, "updated_at": "...", "source_message_id": "msg_..." }
    ],
    "updated_at": "..."
  },
  "inactive_facts": []    // only when include_inactive_facts
}
```

#### 7.2.8 `profile.update` (FR-4.4/4.5/4.6) — request/reply

Request fields:

| Field | Type | Optional | Notes |
| --- | --- | --- | --- |
| `fact_id` | string | optional | client-supplied; else memory_service generates `fact_<hex>` |
| `fact_type` | string | required | e.g. `dietary`, `dob`, `contact_preference` |
| `subject` | string | optional | grouping key; default `""` |
| `text` | string | required | the fact value |
| `source_message_id` | string | optional | when the fact came from a chat message |
| `basic_info_fields` | object | optional | explicit basic-info updates; only these fields may change (FR-4.6) |
| `idempotency_key` | string | optional | default `fact:{fact_id}` if given, else derived from request hash |

Result:
```jsonc
{
  "fact": { "fact_id": "fact_...", "user_id": "user_1", "fact_type": "dietary",
    "subject": "", "text": "avoids gluten", "status": "active", "version": 2,
    "superseded_by": null, "updated_by": "agent_1", "source_message_id": "msg_...",
    "created_at": "...", "updated_at": "..." },
  "superseded": [ { "fact_id": "fact_...", "version": 1, "superseded_by": "fact_..." } ],
  "profile": { "user_id": "user_1", "basic_info": {...}, "active_facts": [...] },
  "basic_info": { "updated_fields": [], "account_authoritative_conflicts": [] }
}
```
`basic_info.updated_fields` lists fields applied; `account_authoritative_conflicts`
lists fields rejected because account data differs (FR-4.6).

### 7.3 Error taxonomy

The reply payload carries the `DomainResultPayload` fields `error` (human
message) and `retryable` (bool). The structured code lives in
`result.error.code` (mirrored as `retryable`/`error` at the envelope level, per
the existing helper/domain handler convention).

| code | HTTP-ish | retryable | Meaning |
| --- | --- | --- | --- |
| `validation_error` | 400 | no | malformed request or invalid field |
| `unauthorized` | 401 | no | missing/invalid service token |
| `forbidden` | 403 | no | caller service not allowed, or `agent_id` mismatch |
| `not_found` | 404 | no | session/message/profile not found |
| `conflict` | 409 | no | idempotency key reused with a different payload; fact supersession race |
| `unavailable` | 503 | yes | broker or retrieval index dependency down |
| `internal_error` | 500 | yes | unexpected failure |
| `upstream_error` | 502 | yes | retrieval_service hand-off failed (indexing/search) |

`result` on failure is `{"ok": false, "error": {"code": "...", "message": "...", "retryable": true|false}}`.

---

## 8. Scoping Enforcement (end-to-end)

`owner_user_id` and `agent_id` are derived from the caller's **verified service
identity**, never from client-supplied owner IDs (FR-3.4).

- conversation-server authenticates to the broker by attaching a signed HS256
  service token in the envelope `headers` (`Authorization`). The token is minted
  with `simple_agent_service_auth.create_service_token` (`libs/service-auth`) and
  carries `svc`, `actor_user_id`, `actor_role` claims.
- memory_service verifies the token with the same signing key (the verification
  function is mirrored in `qdrant_rag_server/shared/` — see design doc §2) and
  requires:
  - `svc` in an allowed-service set (default `{"conversation-server"}`; configurable
    via `MEMORY_ALLOWED_SERVICES`),
  - `actor_user_id` non-empty, non-whitespace, <= 128 chars → **becomes
    `owner_user_id`** for the whole request (the ≤128 length bound is enforced
    in `memory_service.domain_handler._build_scope` after token verification),
  - `X-Actor-User-ID` header equals the token's `actor_user_id` (defense in depth),
  - `X-Agent-ID` header present and, for agent-scoped operations (`session.start`,
    `message.record`, `memory.compress`), equal to the request payload `agent_id`;
    for user-scoped operations it is present but not payload-compared.
- `agent_id` is caller-asserted (the token carries no agent claim). It is trusted
  because the verified caller (conversation-server) enforces agent ownership at
  its own conversation/chat boundary (`verify_owned_active` against
  agent-server). An agent-ownership cross-check inside memory_service is a
  declared defense-in-depth follow-up.
- Every SQL query for messages, memory, or facts is bounded by
  `owner_user_id` AND (`agent_id` when agent-scoped) in the WHERE clause; a
  scope mismatch returns `forbidden`/`not_found`.
- Local/fake mode uses the **same** token-verification code path: the fake
  memory client mints a real token with the local signing key
  (`local-dev-signing-key`), so there is no separate "fake auth" logic.

---

## 9. Idempotency Policy

| Operation | Idempotency key (default) | Dedup behavior |
| --- | --- | --- |
| `session.start` | `session:{session_id}` | existing `session_id` → return existing record, `replayed=true`, no insert |
| `message.record` | `message:{message_id}` | existing `message_id` → return existing record, `recorded=false`; `UNIQUE(session_id, sequence_number)` also guards sequence collisions |
| `session.close` | `session.close:{session_id}` | already closed → `changed=false` |
| `memory.compress` | `compress:{session_id}:{start_sequence}:{end_sequence}:{keep_recent}:{policy}` | the key uses the **request** span fields; the deterministic `memory_id = mem_sum_<sha256({session_id}|{covered_from}|{covered_to}|{policy})[:24]>` uses the **adjusted** covered range (`to = end_sequence - keep_recent`). Existing summary for the span → return it, `replayed=true`. This satisfies FR-2.6 exactly. |
| `profile.update` | `fact:{fact_id}` if given, else request-hash-derived | existing `fact_id` → return stored fact (replay); a repeated identical update to the same `(user_id, fact_type, subject)` supersedes the prior one (this is the intended FR-4.5 update semantics, not a duplicate) |
| `memory.lookup`, `memory.sources`, `profile.read` | — (read-only) | no idempotency key required |

Implementation:
- Mutating operations record `(idempotency_key, operation, request_hash,
  result_json)` in `idempotency_records` within the same SQLite transaction as
  the write.
- On a key hit: compare `request_hash` (sha256 of the canonical `request`
  JSON). Match → return stored `result_json` with `replayed=true`. Mismatch →
  `conflict` (409), non-retryable.
- Compression additionally derives a deterministic `memory_id` from the span
  content so that even a retry that lost its idempotency row cannot duplicate
  the summary (unique `memory_records.memory_id`).

---

## 10. Acceptance Criteria (testable)

Each criterion maps 1:1 to a test case in `tests/memory/` (unit with
in-memory repository) and/or `tests/integration/` (broker wiring).

- **AC-1 (FR-1.1)** `session.start` creates a `sessions` row; issuing it twice
  with the same `session_id` returns the existing row with `created=false`.
- **AC-2 (FR-1.2)** `message.record` persists `(message_id, session_id, role,
  sequence_number, content, owner_user_id, agent_id)`; re-recording the same
  `message_id` does not duplicate the row (`recorded=false`).
- **AC-3 (FR-1.5)** Messages for one session are stored in ascending
  `sequence_number`; a duplicate `(session_id, sequence_number)` is rejected or
  deduped without corrupting order.
- **AC-4 (FR-1.4)** `session.close` sets `status='closed'` and `closed_at`; a
  closed session still returns its messages in `memory.lookup`.
- **AC-5 (FR-2.3/2.4)** `memory.compress` returns a non-empty
  `condensed_context`, persists one `memory_records` row with
  `kind='compression_summary'` and the correct `covered_from`/`covered_to`, and
  is retrievable by later lookups.
- **AC-6 (FR-2.6)** `memory.compress` for the same span twice returns the same
  `memory_id` and `replayed=true` on the second call; exactly one summary row
  exists.
- **AC-7 (FR-3.2/3.3)** `memory.lookup` returns per-source `results` keyed by
  source, each item `{source, source_id, text, score}`; every requested source
  appears in `sources`/`consulted` even with zero matches.
- **AC-8 (FR-3.4/§8)** A lookup with an owner-supplied `user_id` in the payload
  is **ignored** (the request `user_id` field is never read; only the verified
  token's `actor_user_id` bounds the results); a token for a different user
  returns no other user's data.
- **AC-9 (FR-4.2)** A consumed `identity.user.registered` event (no `.v1`
  suffix) creates a `user_profiles` row with `basic_info` populated from the
  event.
- **AC-10 (FR-4.5)** `profile.update` marks the existing active fact
  `(user_id, fact_type, subject)` inactive with `superseded_by` set and inserts
  the replacement active with `version+1`; the unique partial index allows
  exactly one active row per key.
- **AC-11 (FR-4.7)** Every fact write records `updated_by`, `created_at`,
  `updated_at`, and `source_message_id` when supplied.
- **AC-12 (FR-4.6)** A `profile.update` with `basic_info_fields` conflicting
  with account data leaves account-authoritative values intact and reports them
  in `account_authoritative_conflicts`.
- **AC-13 (§9)** Mutating operations with a repeated `idempotency_key` and the
  same request hash replay the stored result; a different payload under the same
  key returns `conflict` (409).
- **AC-14 (§7.1)** Every reply echoes the request `correlation_id` and
  `operation`, and is published to the response topic keyed by `task_id`.
- **AC-15 (§7.3)** Each failure maps to the documented `{code, message,
  retryable}` shape; `retryable` is correctly set for `unavailable`,
  `upstream_error`, `internal_error` and unset for the 4xx family.
- **AC-16 (fake local dev)** The full operation set runs against the SQLite
  repository + fake indexer/searcher + fake identity source with no broker and
  no simple_agent, and every AC-1..15 passes in that mode.
- **AC-17 (FR-3.3)** `memory.sources` returns one entry per requested source with
  `source`, `available`, and a `count`; sources with zero records are still
  reported (consulted).
- **AC-18 (FR-4.8)** `profile.read` returns `profile.basic_info` (from identity)
  and only **active** facts; `include_inactive_facts=true` adds the inactive
  facts without returning them as current.
- **AC-19 (FR-1.4)** A second `session.close` for an already-closed session
  returns `changed=false` (idempotent).

---

## 11. Decisions (resolved open questions)

| # | Question | **Decision** | Rationale |
| --- | --- | --- | --- |
| OQ-1 | Message recording: sync vs async? | **Async fire-and-forget** for `session.start`/`message.record`/`session.close` (durable via broker, per-session ordering via partition key). **Request/reply awaited** for compress, lookup, sources, profile read, profile update. | Chat latency unaffected (FR-1.5); reads need the answer before the caller responds. |
| OQ-2 | Compression method: deterministic vs model-backed? | **v1 deterministic `condense-v1`** (deterministic condensation over the span, `keep_recent` verbatim tail, sentence-boundary extraction). Model-backed summarizer is a follow-up behind the same FR-2 contract (same I/O, different `policy` string). | No LLM dependency in v1; fully deterministic and idempotent (FR-2.6); swappable. |
| OQ-3 | Which spans become memory; retention/TTL for raw messages? | Raw messages stay durably indexed **indefinitely**; compression summaries are **additive** memory records covering `[from, to]`. **Retention/TTL is out of scope** (follow-up). | Auditability + durability; retention adds deletion complexity not needed now. |
| OQ-4 | Who decides a fact is worth persisting? | **The agent sends explicit `profile.update` requests.** Passive extraction from message content is out of scope (follow-up). | Predictable, explicit contract; no ambiguous auto-extraction in v1. |
| OQ-5 | Fact conflict resolution out-of-order? | **Last-write-wins** ordered by `(source_message_id → message.sequence_number if resolvable, else 0; created_at; fact_id)`. | Deterministic total order; matches FR-4.5 replace semantics. |
| OQ-6 | Profile read every turn or on demand? | **On-demand** via `profile.read`/`memory.lookup`. Per-turn injection is conversation-server's decision (inject at session start / after `profile.update`). | Keeps the chat path lean; profile is small so on-demand reads are cheap. |
| OQ-7 | Where does identity data live; who owns `basic_info` writes? | **identity-server owns account data.** memory_service owns the profile/facts projection: `basic_info` is a read-model copy reconciled from **identity events** (primary) or direct reads (backfill). Account data is authoritative on conflict (FR-4.6). | One-writer per table; event-driven profile init decouples lifecycle and is testable with a fake identity source. |

---

## 12. Reference Files (actual current paths)

RAG service (this repo):

- Broker domain contract: `shared/contracts/messages.py` (`MessageEnvelope`,
  `MessageType.DOMAIN_COMMAND`/`DOMAIN_RESULT`)
- Domain payload shapes: `shared/contracts/task_messages.py`
  (`DomainCommandPayload`, `DomainResultPayload`)
- Reserved topics: `shared/contracts/topics.py`
  (`domain.memory.commands` / `domain.memory.results`,
  `domain_command_topic("agent_memory")`)
- Reserved data type: `shared/contracts/data_types.py`
  (`DataType.AGENT_MEMORY`, owner `memory_service`)
- Domain-service reference template (mirror this structure):
  - `workflow_log_service/models.py`
  - `workflow_log_service/repository.py`
  - `workflow_log_service/domain_handler.py`
  - `workflow_log_service/domain_app.py`
  - `workflow_log_service/worker.py`
- Reserved service package: `memory_service/` (currently empty `__init__.py`)
- Existing memory-domain schemas (owned by retrieval_service; reused for the
  vector-index hand-off): `retrieval_service/memory/schemas/scope.py`,
  `retrieval_service/memory/schemas/jobs.py`,
  `retrieval_service/memory/schemas/documents.py`
- Retrieval core primitives: `retrieval_service/core/schemas/document.py`,
  `retrieval_service/core/schemas/scope.py`,
  `retrieval_service/core/schemas/common.py`
- Retrieval transport contracts / error envelope:
  `retrieval_service/retrieval/contracts.py`
- Retrieval index hand-off contract: `retrieval_service/indexing/commands.py`,
  `retrieval_service/indexing/service.py`
- Public edge (unchanged by this work): `manager_service/server/grpc/server.py`
- Architecture/service boundaries: `docs/architecture.md`,
  `docs/service-boundaries.md`
- Reference test structure: `tests/workflow_log/test_domain_handler.py`,
  `tests/integration/test_broker_first_message_flow.py`

Simple Agent repo (`/home/bruce/workspace/simple_agent`):

- Chat saga (compression/lookup injection point):
  `services/conversation-server/src/conversation_server/application/provider_saga.py`
- Message lifecycle (`sequence_number`, `message_id`):
  `services/conversation-server/src/conversation_server/application/chat_service.py`
- Conversation lifecycle (`conversation_id`):
  `services/conversation-server/src/conversation_server/application/conversation_service.py`
- conversation-server service auth:
  `services/conversation-server/src/conversation_server/infrastructure/service_auth.py`
- Shared service-auth token lib:
  `libs/service-auth/src/simple_agent_service_auth/tokens.py`
- Adapter boundary rule: `docs/architecture/future-resource-adapters.md`
- Broker/event communication policy: `docs/architecture/service-communication.md`
- Identity event outbox + payload:
  `services/identity-server/src/identity_server/infrastructure/sqlite_identity_repository.py`
  (`_enqueue_identity_event`, `identity.user.registered`)
- identity-server outbox worker:
  `services/identity-server/src/identity_server/worker.py`
- conversation-server OpenAPI (wiring/docs update):
  `contracts/openapi/conversation-server.yaml`
