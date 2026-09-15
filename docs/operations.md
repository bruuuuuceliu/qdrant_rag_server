# Operations Runbook

This runbook covers the broker-first topology with the **agent-memory integration**
(chat history recording, compression, cross-source lookup, and user profiles).
It is the production runbook for the memory path: how to bring it up, verify it,
secure it, migrate it, back it up, and troubleshoot it.

Authoritative contracts live in `docs/agent-memory-requirements.md` (the locked
spec) and `docs/agent-memory-design.md` (the implementation design, including
§11 Auth/Isolation and §12 Deployment Topology). Read those before operating
the memory stack.

> **Status note (Sprint C):** RAG commits land this sprint; Simple Agent stays
> uncommitted. Items below marked **[planned C#]** or **TODO** are Sprint-C
> workstreams that were in flight at the time of writing (C2 reproducible stack,
> C3 embedding migration, C5 SASL/TLS, C6 operational readiness). Verify against
> the committed code before relying on them.

---

## 1. Start

### 1.1 The production memory path (what must be running)

The memory feature is broker-first: Simple Agent services publish domain
commands on Redpanda; the RAG `memory_service` persists to Postgres and hands
vector work to the RAG retrieval workers; Qdrant serves the vector index.
Production runs **every** memory mode in `broker` (never `fake`).

Required processes/components:

| Component | Identity | Notes |
| --- | --- | --- |
| Redpanda | `redpanda-rag-local` | **Dual listener**: `PLAINTEXT://127.0.0.1:9092` (local-dev only) + `INTERNAL://redpanda-rag-local:19092` on the private `rag-memory-test` network. Production clients reach the **internal** listener only. |
| Qdrant | `qdrant-rag-local:6333` (REST) / `:6334` (gRPC) | Vector index. Reachable only from the RAG/memory stack + SA mesh over the private network. |
| `memory_service` worker | `python -m memory_service.worker` | Consumes `domain.memory.commands` (group `memory_service`), replies on `domain.memory.results`; owns the Postgres memory DB; consumes `identity.user.events` (group `memory_service.identity`, raw) and `helper.retrieval.results` (group `memory_service.retrieval`). |
| Retrieval index worker | `python -m retrieval_service.indexing.worker` | Consumes `helper.retrieval_index.commands` (`memory_ingest`), embeds + upserts Qdrant. Creates the memory collections lazily on first ingest. |
| Retrieval helper worker | `python -m retrieval_service.server.worker` | Consumes `helper.retrieval.commands` (`memory_search`), serves semantic lookup. |
| RAG broker-first core | Redis status node, db_node, storage node, task manager, task service, workflow log | Required for the full local parity stack; the memory path itself needs broker + Qdrant + the three memory-related workers above. |
| Simple Agent conversation-server | `conversation-server-api` (:8050) + worker | Publishes memory commands; **must set `REDPANDA_BOOTSTRAP_SERVERS=redpanda-rag-local:19092`** and join the `rag-memory-test` network. `memory.client_mode: broker` in production. |
| Simple Agent identity-server | `identity-server-worker` | Publishes `identity.user.events`; **must set `REDPANDA_BOOTSTRAP_SERVERS=redpanda-rag-local:19092`**, join `rag-memory-test`, and set `REDPANDA_ENABLED=true`. |

Key env for the RAG memory workers in production:

```bash
# Broker transport: bare topics (no prefix) so SA and RAG share the same names.
BROKER_TOPIC_PREFIX=""
# Internal listener on the private network in production:
BROKER_BOOTSTRAP_SERVERS=redpanda-rag-local:19092
# (Local parity may use the dev PLAINTEXT listener instead:)
# BROKER_BOOTSTRAP_SERVERS=127.0.0.1:9092

# Memory service: all modes broker (never fake in production).
MEMORY_IDENTITY_MODE=broker
MEMORY_INDEX_MODE=broker
MEMORY_SEARCH_MODE=broker
RAG_POSTGRES_URL=postgresql://rag:...@postgres:5432/rag
MEMORY_COLLECTION=agent_memory
MEMORY_DOCUMENTS_COLLECTION=agent_documents
MEMORY_ALLOWED_SERVICES=conversation-server,just-agent-server

# Embeddings: production is local bge 768-dim.
RAG_EMBEDDING_PROVIDER=local
RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RAG_EMBEDDING_DIMENSION=768
```

Secrets (see §3): `SERVICE_AUTH_SIGNING_KEY` **must equal** Simple Agent's
signing key. Issuer/audience/TTL must match Simple Agent's `x-service-auth`
(`simple-agent-local` / `simple-agent-internal` / `300` — §3.1, §11.9).

### 1.2 Local parity with the run-all helper

For local development and reproducible bring-up, `examples/local/run-all.sh`
starts the broker-first composition. See `configs/local.env.example` and
`configs/memory/local.env.example` for the local settings.

```bash
# Full local stack (defaults: Redpanda 127.0.0.1:9092, Qdrant, all workers):
examples/local/run-all.sh --reset --init

# Verified ingest/search smoke:
examples/local/run-all.sh --reset --smoke
# (CI local-smoke uses deterministic/384 to avoid a model download:
#   --embedding-provider deterministic --embedding-model deterministic-hash
#   --embedding-dimension 384)

# Infrastructure-only gate (Redpanda + Redis, no Qdrant, no services):
examples/local/run-all.sh --infra-only
```

**[C2, implemented]** `examples/local/run-all.sh --memory` brings up the
**full production-shape memory stack** — Redpanda with the dual listener
(`--advertise-kafka-addr PLAINTEXT://127.0.0.1:9092,INTERNAL://redpanda-rag-local:19092`),
the `rag-memory-test` Docker network, Qdrant, `memory_service`, and the two
retrieval workers — with `BROKER_TOPIC_PREFIX=""`, `MEMORY_DB_PATH` under
`.run/`, an explicit `SERVICE_AUTH_SIGNING_KEY`, WAL enabled, and the bge-768
embedding env. `stop-all.sh` stops the memory worker via its PID file and the
module-pattern fallback, leaving no orphans. For the container-to-broker path,
Redpanda is created/attached on the external `rag-memory-test` network when
`--memory` is set (a pre-existing single-listener Redpanda container is attached
to the network but still needs a `stop-all.sh`/recreate to gain the INTERNAL
listener).

Stop everything with `examples/local/stop-all.sh` (`--clean` to remove runtime
files, `--clean-data` to also remove the local data directory and volumes).

### 1.3 Validating live infrastructure outside the runner

```bash
examples/local/run-all.sh --infra-only
RAG_LIVE_INFRA=1 pytest -m live_infra tests/integration/test_live_infra_smoke.py -q
```

The GitHub Actions workflow runs the full non-live suite on pushes and pull
requests; its manual `workflow_dispatch` inputs run the Docker-backed live-infra
tests or the full local ingest/search smoke.

### 1.4 Manual production bring-up (when not using a runner)

1. **Broker**: start Redpanda with both listeners. Local dev: the `run-all.sh`
   Redpanda container publishes `127.0.0.1:9092`. Production: the internal
   listener `redpanda-rag-local:19092` exists only on the private
   `rag-memory-test` network; do **not** publish it to a public interface
   (design doc §11.1). **[planned C2]** the run-all helper owns this wiring and
   creates the network.
2. **Topics**: bootstrap the canonical topic set. The runner does this via
   `broker_service.bootstrap.bootstrap_topics`. For the memory path the topics
   of interest are `domain.memory.commands`, `domain.memory.results`,
   `identity.user.events`, `helper.retrieval_index.commands`,
   `helper.retrieval.commands`, `helper.retrieval.results`.
3. **Qdrant**: reachable at `localhost:6333` (or the private-host equivalent).
   Collections are created lazily by the retrieval index worker on first ingest
   (§5 covers dimensions).
4. **Retrieval workers** (both must be up for lookup):
   ```bash
   python -m retrieval_service.indexing.worker   # memory_ingest -> Qdrant
   python -m retrieval_service.server.worker     # memory_search
   ```
5. **memory_service**:
   ```bash
   python -m memory_service.worker
   ```
   Broker mode is the default; it **fails fast at startup** if any
   `MEMORY_*_MODE=broker` and `SERVICE_AUTH_SIGNING_KEY` is missing/empty
   (§3).
6. **Simple Agent** (uncommitted working tree): conversation-server
   (api + worker) with `memory.client_mode: broker` and
   `REDPANDA_BOOTSTRAP_SERVERS=redpanda-rag-local:19092`; identity-server-worker
   with the same bootstrap env and `REDPANDA_ENABLED=true`. Both join the
   `rag-memory-test` network (compose declares it `external: true`; the RAG
   stack creates it).
7. **Verify**: run the readiness report (§2), then drive a chat or a direct
   memory command and confirm a profile row + Postgres rows + Qdrant points.

---

## 2. Readiness

### 2.1 The readiness report

`python -m deployment.composition.readiness` prints a JSON report and exits
non-zero if any check is not ready. `--skip-qdrant` is for the infra-only
broker/Redis gate. `run-all.sh` calls it before service startup and again after
Qdrant is reachable (`verify_broker_first_readiness`).

Current checks and what **healthy** looks like:

| Check | Healthy when |
| --- | --- |
| `broker` | `ok=true`; canonical topic set from `shared.contracts.TOPICS` present; `bootstrap_servers`/`topic_prefix` correct; `missing_topics` empty. Optional lag probes (`BROKER_LAG_TARGETS` in `group_id:topic,topic;...` format) are reported in details and do not fail startup when required topics are healthy. |
| `redis` | `PING` ok; task-status write/read ok; completed-task TTL positive. |
| `storage` | Owned local storage root is writable and allocatable (probe file write+read). |
| `postgres` | RAG Postgres reachable; readiness database allocated; schema version recorded; health snapshot stored in the db_node control-plane tables. |
| `qdrant` | `/collections` endpoint returns 2xx. |

**[C6, implemented]** the report now includes `memory` and `retrieval` checks
alongside `broker`/`redis`/`storage`/`postgres`/`qdrant`:

- `memory` — verifies `MemoryServiceSettings` build (the B3 signing-key guard:
  broker modes require a non-empty `SERVICE_AUTH_SIGNING_KEY`), the
  `MEMORY_DB_PATH` parent is writable, and `PostgresMemoryRepository.initialize()`
  succeeds (schema created, WAL enabled). Details show `db_path`,
  `identity_mode`/`index_mode`/`search_mode`, `signing_key_set`, and
  `db_exists`.
- `retrieval` — verifies the retrieval worker data paths are writable:
  `RETRIEVAL_PLACEMENT_DB_PATH` and `RAG_RESPONSE_CACHE_DB_PATH` parents.

The worker-level `health()` payload (`service`, `ready`, `dependencies`,
`details`) remains available in the running `memory_service.worker` context (see
§2.2) and is surfaced through the worker's runtime-health object.

### 2.2 Verifying a running memory_service by hand

The worker exposes a runtime-health object but is broker-only (no HTTP port).
Signals of health from logs/state:

- Startup completes (no broker-mode guard exception — §3).
- Consumers attach to `domain.memory.commands`, `identity.user.events`, and
  `helper.retrieval.results` (groups `memory_service`,
  `memory_service.identity`, `memory_service.retrieval`).
- Postgres schema initializes at `MEMORY_DB_PATH` (`sessions`, `messages`,
  `memory_records`, `user_profiles`, `user_facts`, `idempotency_records`).
- A driven command returns a correlated `DOMAIN_RESULT` on
  `domain.memory.results`.

---

## 3. Secrets

### 3.1 `SERVICE_AUTH_SIGNING_KEY` — the single signing-key contract

The whole memory surface is authenticated by **one shared HS256 signing key**:

- conversation-server mints service tokens with
  `simple_agent_service_auth.create_service_token`.
- RAG `memory_service` verifies them with `shared/service_auth.py`, a
  dependency-free mirror of the Simple Agent library (same algorithm, header,
  claims, and local-dev defaults).

`SERVICE_AUTH_SIGNING_KEY` **must equal** Simple Agent's
`SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY`. Drift breaks every token verification:
conversation-server tokens will not verify → `401`/`403` on every memory
command (see §7). Issuer/audience/TTL must also match. Both production composes
and local `run-all.sh --memory` pair on `simple-agent-local` /
`simple-agent-internal` / `300` (SA compose.production.yaml `x-service-auth`,
line 64; RAG compose default — see §11.9).
`MEMORY_ALLOWED_SERVICES` must include `conversation-server` and `just-agent-server`.

### 3.2 The B3 broker-mode guard

`memory_service/config.py` **fails fast** when any of
`MEMORY_IDENTITY_MODE`/`MEMORY_INDEX_MODE`/`MEMORY_SEARCH_MODE` is `broker` and
`SERVICE_AUTH_SIGNING_KEY` is unset, empty, or whitespace-only (an empty
but-present key would otherwise silently pass startup and then 401 on every
request). The error message states the single-contract requirement. `fake`
modes and direct construction bypass the guard.

### 3.3 Where the key is set

- RAG production env: `configs/production.env.example` declares
  `SERVICE_AUTH_SIGNING_KEY=` as **required, no default**.
- Simple Agent: the compose stack requires
  `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY` (`:?SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY is required`)
  and injects it as `SERVICE_AUTH_SIGNING_KEY` into conversation-server and
  identity-server.

In production the operator sets the **same secret value** in both places
(prefer a secret manager; never commit it).

---

## 4. SASL/TLS (broker transport security)

The production broker uses **SASL/SCRAM + TLS** on the internal
`redpanda-rag-local:19092` listener. RAG `broker_service` (`BrokerSettings`,
`create_redpanda_bus`, `RedpandaProducer/Consumer/Admin`) and Simple Agent's
memory client / identity publisher accept SASL/TLS from env. Local development
keeps the PLAINTEXT `127.0.0.1:9092` listener.

Env keys (implemented by C5):

- `BROKER_SECURITY_PROTOCOL` — `PLAINTEXT`, `SSL`, `SASL_PLAINTEXT`, or
  `SASL_SSL`. Production: `SASL_SSL` (`SASL_PLAINTEXT` for dev over the private
  network without TLS).
- `BROKER_SASL_MECHANISM` — `PLAIN`, `SCRAM-SHA-256`, or `SCRAM-SHA-512`.
  Production: `SCRAM-SHA-256`.
- `BROKER_SASL_PLAIN_USERNAME` / `BROKER_SASL_PLAIN_PASSWORD` — SCRAM
  credentials (the password is a secret; never commit it).
- `BROKER_SSL_CAFILE` — path to the CA that signed the broker cert (required
  for `SSL`/`SASL_SSL`; must exist at startup).
- `BROKER_SSL_CERTFILE` / `BROKER_SSL_KEYFILE` — optional client certificate /
  key for mutual TLS.

`BrokerSettings.validate()` fails fast at startup on an unknown protocol,
missing SASL credentials, or a missing CA file, and `BrokerSettings.redacted()`
masks `sasl_plain_password` so settings can be logged safely.

Operational rules:

- If SASL/TLS is enabled on the internal listener, **every** memory-path client
  must present the same credentials — RAG memory/retrieval workers **and** SA
  conversation-server/identity-server. A credential mismatch surfaces as broker
  connection/auth failures in the worker logs.
- Keep the PLAINTEXT listener host-local and dev-only. Never expose it on the
  `rag-memory-test` network or a public interface.
- Verify the SASL path with a throwaway Redpanda before promoting:
  `examples/local/verify-sasl.sh` (per C5); the live stack may remain on
  PLAINTEXT until the swap is verified.

---

## 5. Embeddings migration (384 → 768)

### 5.1 Production embedding

Production embeddings come from **local `sentence-transformers`
`BAAI/bge-base-en-v1.5` (768-dim)** via `retrieval_service/embedding/local.py`
(`LocalSentenceTransformerEmbedding`; factory maps `local` → it). The default
config is `RAG_EMBEDDING_PROVIDER=local`, `RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5`,
`RAG_EMBEDDING_DIMENSION=768`. The deterministic bag-of-words provider (384-dim)
remains for tests and local/offline smoke runs.

Note: `sentence-transformers` is installed; `fastembed` is **not**, so the
memory path is dense-only (no sparse/BM25) — accepted. Memory collections
(`agent_memory`, `agent_documents`) carry a fixed dense dimension.

### 5.2 The migration

Memory collections carry the embedding dimension baked in at creation. Switching
from deterministic-384 (live test data) to bge-768 requires **re-indexing**:

- **Option A — delete-and-reindex** (fine for throwaway/deterministic test
  data): stop ingest, delete the stale-dimension collections (`agent_memory`,
  `agent_documents`), restart with 768, re-ingest.
- **Option B — versioned collection names** (preferred for zero-downtime):
  point at new names such as `agent_memory_v768` / `agent_documents_v768` via
  `MEMORY_COLLECTION` / `MEMORY_DOCUMENTS_COLLECTION`, re-ingest into the new
  names, then cut over. Existing rows keep their ingest-time collection
  (`memory_records.collection_name`), so `memory.lookup` resolves the right
  collection per row (§7.2.5 of the requirements).

**TODO(C3/Dev 2):** the exact choice (delete-and-reindex vs versioned names) is
a C3 recommendation that was in flight; adopt the committed C3 decision.

### 5.3 Stale-dimension collections fail loudly (after C3)

Today `_validate_hybrid_collection_schema` (`retrieval_service/services/vector_store.py`)
checks vector **names** only, not **size**, so a stale 384-dim collection passes
schema validation and then fails at the first 768-dim upsert (dimension
mismatch). **[planned C3]** fixes the validator to check the dense vector **size**
against the configured dimension, so a stale-dimension collection is rejected
loudly at validation (collection-level) instead of failing at upsert. After C3,
a leftover 384-dim `agent_memory`/`agent_documents` collection will block
indexing until it is deleted or the versioned name is used.

**[planned C4]** optionally adds HNSW/indexing config (`m`, `ef_construct`,
`indexing_threshold`, `prevent_unoptimized`) to memory collection creation with
sane defaults. Until C4 lands, collections are created with Qdrant defaults.

---

## 6. Backup / restore

### 6.1 Memory DB (Postgres)

The durable memory store lives in the shared RAG Postgres database, resolved
from `RAG_POSTGRES_URL` (or the `MEMORY_DB_URL` override) and owned by
`PostgresMemoryRepository.initialize()`. The durable Postgres database is the
primary backup target (see `deployment/backup.py` §11.7 for the `pg_dump`
path).

Recommended backup (consistent, online-safe):

```bash
pg_dump -Fc -f "/backup/agent_memory-$(date +%F).dump" "${RAG_POSTGRES_URL}"
```

Restore:

1. Stop `memory_service`.
2. Restore the dump into the RAG Postgres database:
   sidecars if restoring a WAL snapshot).
3. Start `memory_service`; the schema initializes idempotently (`CREATE TABLE
   IF NOT EXISTS` + in-place migrations).

### 6.2 Qdrant collections

Vector points are a **projection** of the Postgres source of truth (design §9):
if Qdrant is lost, re-indexing from `memory_records` rebuilds it (the re-drive
seam). **[C6, implemented]** on `memory_service` startup the worker re-queues
`memory_records` where `indexed=0` through the existing indexer
(`memory_service.reconciliation.reconcile_pending_index`), grouping documents
into their ingest-time collection; failures are logged and the records stay
pending for the next startup. This is a minimal startup reconciliation, not a
scheduler — a periodic re-index job remains a documented follow-up. For
point-in-time fidelity, snapshot the collections:

```bash
curl -X POST "http://qdrant-rag-local:6333/collections/agent_memory/snapshots"
curl -X POST "http://qdrant-rag-local:6333/collections/agent_documents/snapshots"
```

Cross-cluster collection migration/import is out of scope; snapshots are local
to the Qdrant node. Prefer re-index over snapshot restore for the memory
collections unless you need exact point state (scores/IDs).

### 6.3 What is recoverable

| Store | Recoverable | Notes |
| --- | --- | --- |
| Postgres memory DB | **Fully** — sessions, messages, memory records, profiles, facts, idempotency | Primary backup target. |
| Qdrant vectors | Rebuildable from Postgres via re-index; snapshot for exact point state | `agent_memory`, `agent_documents`. |
| Redis task status | Ephemeral (TTL), not memory data | No backup needed. |
| Redpanda topics | Not a memory backup | Transient unless retained; offsets replayed by consumer groups. |

---

## 7. Troubleshooting

### 7.1 Memory-specific failure modes

| Symptom | Likely cause | Check / fix |
| --- | --- | --- |
| Every memory command → `401 unauthorized` / `403 forbidden` | Signing-key drift or issuer/audience mismatch (§3.1); `svc` not in `MEMORY_ALLOWED_SERVICES` | Confirm `SERVICE_AUTH_SIGNING_KEY` equals `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY`; issuer/audience/TTL match; `MEMORY_ALLOWED_SERVICES` includes `conversation-server` and `just-agent-server`. |
| `memory_service` won't start | B3 broker-mode guard (§3.2) — any `MEMORY_*_MODE=broker` with missing/empty/whitespace `SERVICE_AUTH_SIGNING_KEY` | Set a non-empty signing key, or run fake modes for standalone dev. |
| `memory.lookup` → `upstream_error` (502, retryable) | Retrieval workers down (index or search helper) — the hand-off failed (a non-dimension upstream error) | Confirm `retrieval_service.indexing.worker` and `retrieval_service.server.worker` are up and their consumer groups are attached. Lookup is best-effort from SA's side; chat survives. |
| `memory.lookup` returns empty `chat_history`/`documents` (not an error) | Stale-dimension memory collection (§5.3) — a 384-dim `agent_memory` collection queried with a 768-dim embedding | **Contract**: lookup is best-effort and per-source. The dimension mismatch degrades only the vector-backed source(s) to empty and never fails the whole lookup (`results: {chat_history: [], ...}`); facts still resolve from Postgres. Delete/re-version the stale collection and re-ingest to restore hits. |
| Indexing silently not applied (`indexed=false` or no Qdrant points) | Retrieval index worker down; or stale-dimension collection (§5.3) | Check the retrieval index worker log; delete/re-version stale collections and re-ingest. |
| Broker down | Saga best-effort fallback (SA) — chat **survives** on context-v1; memory commands not delivered | Restore Redpanda; memory_service reconnects, rejoins groups, consumes backlog, and integrity re-checks (verified live in Follow-up B). |
| Long user turn appears truncated in memory | 2048-char cap is **by design** | `message.record` `content` and `memory.lookup` `query` are deterministically truncated to a 2048-char prefix server-side — recorded, not dropped (§7.2.2/7.2.5 of requirements). |
| No profile row for a user | Identity event not published, or event is `backfilled` | memory_service applies only `identity.user.registered` and `identity.user.status_changed`; **backfilled events are ignored** (design §11.2). Register a fresh user (or publish a registered event) and confirm the `memory_service.identity` group consumed it. |
| Stale documents lookup returns empty | Documents reachable only out-of-band; SA has no `ingest_documents` client yet (§9, FR-3.1 decision) | Ingest via `memory.documents.ingest` (RAG op) or an out-of-band client. |

### 7.2 General broker-first troubleshooting (unchanged)

- Check `.run/logs/*.log` for process startup failures.
- Run `examples/local/stop-all.sh --clean` before restarting a local topology.
- Validate config with `configs.validation.validate_settings_or_raise`.
- Inspect logical database ownership state in the db_node control-plane tables
  (`db_node_databases`, `db_node_schema_versions`) in the RAG Postgres database.
- If tasks stay `running`, inspect task-service logs and the expected helper
  result topics for missing fan-in results. Durable fan-in state lives in the
  RAG Postgres database (task tables).
- Terminal helper failures publish repair context to `task.dead_letters` by
  default. Retryable helper failures are republished until
  `TASK_SERVICE_MAX_ATTEMPTS`.
- Helper commands and results carry `attempt`; task-service Postgres state records
  dispatch/result attempt history in `task_step_attempts`.
- The broker service owns Redpanda transport, topic bootstrap, health, and lag
  visibility. Task leases, retries, backoff, attempt counts, and dead-letter
  decisions remain task-service responsibilities. The task-service recovery loop
  claims due `next_attempt_at` retries and expired helper leases from Postgres,
  redispatches while attempts remain, and terminally fails expired max-attempt
  helper steps.

---

## 8. Security

The production boundary is **network isolation** (design doc §11 — the
user's auth direction). There is **no custom RAG authentication service** and
**no identity-event signing**.

- **Public surface = Simple Agent only.** `gateway-server :8000` (HTTP edge)
  and `web-server :5173` are the only publicly reachable entry points. **No
  public ingress/LB to `memory_service`, Redpanda, or Qdrant.** In production
  the RAG/memory stack lives on a private VPC/subnet (or private k8s namespace)
  reachable only from the Simple Agent mesh.
- **Private networks.** SA-internal APIs are on the `backend` network
  (`internal: true`). RAG/memory-only surfaces are on the private
  `rag-memory-test` network (SA compose declares it `external: true`; the RAG
  stack creates it): `redpanda-rag-local:19092` (internal listener),
  `qdrant-rag-local:6333/6334`, Redis, memory_service Postgres, and the
  broker-only memory/retrieval workers.
- **The `127.0.0.1:9092` PLAINTEXT listener is a local-dev convenience ONLY.**
- **Trusted-broker identity events.** `identity.user.events` is published by
  identity-server (sole publisher) on the private broker and consumed by
  memory_service **raw (no service token)** under the private-network trust
  boundary. Event forgery requires already being inside the trusted network.
  **Do not build identity-event signing.** Declared follow-up: if the broker is
  ever exposed beyond the private network, identity-event signing + verification
  becomes **required**.
- **Service tokens.** conversation-server attaches an HS256 token (TTL 300,
  `iss`/`aud` checked, `svc` in `MEMORY_ALLOWED_SERVICES`); `actor_user_id`
  becomes `owner_user_id`, and `X-Actor-User-ID` must match the token. Qdrant
  queries filter on `owner_id`/`agent_id` (the memory-aware search path
  overrides the query filter).
- **[planned C5]** adds SASL/SCRAM + TLS on the internal listener (§4).

---

## 9. Release / commit-split status (Sprint C)

Sprint C makes the memory integration production-ready. RAG commits land; Simple
Agent stays **uncommitted** (deferred). SA working-tree edits are allowed where
required (e.g., SASL client support) but are **not** committed.

**Committed this sprint (RAG):** the memory integration (contracts, auth,
`memory_service`, retrieval hand-off, storage-node ingestion request id, tests,
docs incl. the Sprint-B §11 auth/isolation), plus the Sprint-C hardening
(reproducible stack, readiness, embedding migration, broker security).

**Deferred / explicitly not committed:**

- The Simple Agent commit (Sprint-C changes live in the SA working tree only).
- SA `ingest_documents` client — documents are reachable only **out-of-band**
  today (RAG has the `memory.documents.ingest` op; SA has no client yet). This
  is a **declared SA-sprint item** and part of the FR-3.1 product decision
  (§10).
- SA `_render_profile_block` framing follow-up (label/delimiters for injected
  profile text) — only if not already framed this sprint.
- Identity-event signing — only if the broker is ever exposed beyond the
  private network (then it becomes required; design §11.2).
- Model-backed summarization, passive fact extraction, retention/TTL, and
  `history.replay` (requirements §2.4) remain out of scope.

---

## 10. FR-3.1 documents-source decision (for product sign-off)

Requirements FR-3.1 describes the `documents` lookup source as *"RAG
collections attached to the agent (existing document RAG)."* Sprint B (B1)
implemented it as a **distinct `agent_documents` vector collection fed by the
`memory.documents.ingest` op** (owner/agent-scoped, stored on
`memory_records.collection_name`, never mixed into the chat-memory collection).
This is a **deliberate deviation** from the requirement wording: it does **not**
attach the existing project-RAG document collections; it maintains a separate,
owner-scoped documents index inside the memory service.

**Flag for product sign-off:** confirm that the distinct `agent_documents`
collection (ingested via `memory.documents.ingest`) is the intended documents
source, versus wiring the existing project-RAG collections into `memory.lookup`.

**SA-side gap (declared):** Simple Agent has **no `ingest_documents` client**
yet, so documents are reachable only out-of-band. Wiring an SA
`ingest_documents` client to the RAG op is a declared SA-sprint item.

---

## 11. Production Docker Compose deployment

The repo ships a production compose (`deployment/docker-compose.prod.yml`) that
runs the **same service code and broker contracts as local** (structure.md
golden rule): one container per worker, a private `rag-internal` network, and a
shared `rag-data` volume for durable state. Every RAG container runs as the
unprivileged `rag` user (uid 10001) and exposes an ops HTTP surface.

### 11.1 Image

```bash
# Single image serves every service; compose overrides the command per service.
docker build --build-arg INSTALL_CPU_ONLY_TORCH=1 -t qdrant-rag-server:latest .
```

- `INSTALL_CPU_ONLY_TORCH=1` installs the much smaller CPU-only torch wheel.
- `EMBEDDING_MODEL=BAAI/bge-base-en-v1.5` pre-caches the embedding model into
  the image (workers then start offline).
- Secrets are never baked in; `.dockerignore` excludes all `*.env`, certs, and
  keys. Publish the image to GHCR with the manual `publish_images` CI input.

### 11.2 Bring-up

```bash
cp deployment/compose.prod.env.example deployment/.env
# edit deployment/.env: REDIS_PASSWORD, SERVICE_AUTH_SIGNING_KEY, ...

cd deployment
docker compose -f docker-compose.prod.yml up -d
docker compose ps            # every RAG service reports "healthy"
```

Required secrets fail fast at compose parse time (`REDIS_PASSWORD`,
`SERVICE_AUTH_SIGNING_KEY`). Broker SASL/TLS is commented in the compose
`x-rag-env` block (see §4). For a smoke run that avoids the embedding model and
host-port clashes, use the included override:

```bash
REDIS_PASSWORD=x SERVICE_AUTH_SIGNING_KEY=y \
RAG_EMBEDDING_PROVIDER=deterministic RAG_EMBEDDING_MODEL=deterministic-hash RAG_EMBEDDING_DIMENSION=384 \
docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.smoke.yml up -d
```

### 11.3 Ops surface (health, readiness, metrics)

Every RAG worker runs a small HTTP ops server when `RAG_OPS_ENABLED=true`
(production compose sets it): `/healthz` (liveness), `/readyz` (readiness, from
the worker's own dependency checks), and `/metrics` (Prometheus). Ports:

| Service | Ops port |
| --- | --- |
| manager | 9001 |
| task-manager | 9002 |
| task-service | 9003 |
| project | 9004 |
| workflow-log | 9005 |
| ingestion | 9006 |
| retrieval | 9007 |
| retrieval-index | 9008 |
| storage | 9009 |
| db-node | 9010 |
| redis-status-node | 9011 |
| memory | 9012 |

`RAG_OPS_HOST`/`RAG_OPS_PORT` override defaults; `RAG_OPS_ENABLED` defaults off
so the local runner and unit tests are unaffected. Workers shut down gracefully
on SIGTERM/SIGINT (consumers leave their groups, producers flush, stores close),
so orchestrators get clean exits.

### 11.4 Observability

- **Logs**: `RAG_LOG_FORMAT=json` (set in the compose) emits one JSON object per
  line with `correlation_id` threaded from broker messages; `RAG_LOG_LEVEL`
  controls verbosity.
- **Metrics**: the compose starts Prometheus (`deployment/prometheus.yml`
  scrapes every ops port plus the Redis exporter) at `:9090`. Key series:
  `rag_tasks_accepted_total`, `rag_tasks_completed_total`,
  `rag_tasks_failed_total`, `rag_broker_messages_produced_total`,
  `rag_broker_messages_consumed_total`, `rag_http_requests_total`,
  `rag_ops_ready`.
- **Tracing** (optional): set `RAG_OTEL_ENDPOINT` to an OTLP/gRPC collector and
  install the extras (`pip install "qdrant-rag-server[tracing]"`); the broker
  publish/consume path emits spans keyed by the message correlation/task ID.

### 11.5 Public-edge guards

The manager gRPC API enforces a token-bucket rate limit and a per-message
payload cap (`MANAGER_RATE_LIMIT_REQUESTS_PER_SECOND`,
`MANAGER_RATE_LIMIT_BURST`, `MANAGER_MAX_REQUEST_BYTES`; defaults 100/200/4 MiB).
Requests past the limit receive `RESOURCE_EXHAUSTED`; oversized messages are
rejected at the transport. Health checks are **not** rate limited.

### 11.6 Secrets

The config layer resolves `<KEY>_FILE` for any secret: set
`SERVICE_AUTH_SIGNING_KEY_FILE=/run/secrets/signing_key` and the file's content
(trailing newline stripped) becomes the value. This is the Docker secret /
k8s `secretKeyRef` pattern and how a secret manager materializes credentials.
Covered secrets include `BROKER_SASL_PLAIN_PASSWORD`, `SERVICE_AUTH_SIGNING_KEY`,
and any value the settings loaders read. Never commit `*.env` or cert material.

### 11.7 Backup / restore

`deployment/backup.py` snapshots the RAG Postgres durable stores via `pg_dump`
(`--pg-url`, defaulting to `RAG_POSTGRES_URL`) plus Qdrant collection snapshots
into a timestamped directory with rotation (`--keep`). Run it from the compose
backup service:

```bash
docker compose --profile backup run --rm backup
```

Schedule it from host cron or a k8s CronJob. Restore steps are in §6; a restore
drill (backup → restore to a scratch DB → verify) is covered by unit tests and
the manual `container-smoke` CI job.

### 11.8 CI gates

`.github/workflows/ci.yml` runs, on every push/PR: ruff lint, pip-audit
dependency scanning, and the full pytest suite with a coverage floor. Manual
`workflow_dispatch` inputs additionally run Docker-backed live-infra tests, the
full local smoke, a container-topology smoke (build → compose up → health
probes → live backup → SIGTERM graceful-exit check), and image publication to
GHCR.

### 11.9 Integrated Simple Agent deployment (shared `rag-memory-test` network)

Simple Agent's production compose participates in the broker-first memory stack
over **one shared private Docker network** (`rag-memory-test`) and **one shared
Redpanda broker** (INTERNAL listener `redpanda-rag-local:19092`). This compose
**creates** the network and the broker; SA's compose declares the network
`external: true` and only joins. Design: `docs/design/sa-integration-topology.md`;
acceptance list: `docs/design/sa-integration-spec.md` §8.

**Bring-up order (exact):**

1. **RAG stack first** — creates `rag-memory-test` and starts Redpanda:
   ```bash
   cd deployment
   cp compose.prod.env.example .env   # fill REDIS_PASSWORD + SERVICE_AUTH_SIGNING_KEY
   docker compose -f docker-compose.prod.yml up -d
   docker network ls | grep rag-memory-test      # created by this stack
   docker compose -f docker-compose.prod.yml ps  # every RAG service healthy
   ```
2. **Confirm the network before SA comes up** (SA `up` fails if the external
   network is missing):
   ```bash
   docker network inspect rag-memory-test   # lists redpanda at this point
   ```
3. **SA stack second** (in `simple_agent`):
   ```bash
   docker compose -f infra/docker/compose.production.yaml up -d
   docker network inspect rag-memory-test   # now also lists conversation-server-* + identity-server-worker
   ```

The network is idempotent: compose reuses it if it already exists. Caveat: this
applies to a network **compose created**. A `rag-memory-test` pre-created with
`docker network create` (e.g. by a prior `run-all.sh --memory` on the same host)
lacks the compose ownership label; `up` warns and will not attach Redpanda to it.
Before production bring-up on such a host, stop the local stack and remove that
network (`docker network rm rag-memory-test`), or pre-create it with
`docker network create rag-memory-test --internal` and accept the warning.

**Shared-secret requirement.** One shared HS256 key: RAG `SERVICE_AUTH_SIGNING_KEY`
**must equal** SA's `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY` (same value via a
secret manager or `*_FILE`; never committed — §3.1). Issuer/audience/TTL must
match SA's `x-service-auth`: `simple-agent-local` / `simple-agent-internal`
/ `300` in both the RAG and SA production composes (same as local
`run-all.sh --memory`). `MEMORY_ALLOWED_SERVICES` includes `conversation-server`
and `just-agent-server`.
Drift ⇒ `401`/`403` on every memory command.

**Topology and trust surface.**

- Redpanda joins **both** `rag-internal` and `rag-memory-test` with the alias
  `redpanda-rag-local`; all RAG workers and the SA conversation/identity
  services use `redpanda-rag-local:19092` (the INTERNAL listener, `§1.1`).
  `BROKER_TOPIC_PREFIX` is empty (bare topics shared with SA).
- SA joins **only** `rag-memory-test`: reachable members are the broker's
  INTERNAL listener and the RAG memory/retrieval workers. qdrant/redis and the
  worker ops ports stay on `rag-internal`, unreachable from SA (network-isolation
  auth boundary, §8).
- The INTERNAL listener is **not** host-published by either compose. For
  host-run SA broker-mode clients/tests, bring the RAG stack up with the interop
  override, which publishes `127.0.0.1:19092` (host-local only):
  ```bash
  REDIS_PASSWORD=x SERVICE_AUTH_SIGNING_KEY=y \
  RAG_EMBEDDING_PROVIDER=deterministic RAG_EMBEDDING_MODEL=deterministic-hash RAG_EMBEDDING_DIMENSION=384 \
  docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.interop.yml up -d
  ```
  Host-run tests then connect with `REDPANDA_BOOTSTRAP_SERVERS=127.0.0.1:19092`.

**Verify end-to-end:** run the readiness report (§2), confirm
`docker network inspect rag-memory-test` lists containers from **both** stacks,
then drive a chat (`session.start`/`message.record` → Postgres rows, `memory.lookup`
returns per-source results) and register a user (`identity.user.registered` →
`user_profiles` row).
