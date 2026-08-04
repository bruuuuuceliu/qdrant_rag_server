# Simple Agent <-> RAG Memory Integration — Production Wiring Spec

Status: **Authoritative integration spec** (drives the production compose work in
both repos). Owners: qdrant_rag_server (memory_service / broker) and simple_agent
(publishers). Supersedes any draft wiring described in sprint notes; where this
doc disagrees with a compose file, this doc is the target.

Companion docs (read first): `docs/agent-memory-requirements.md` (locked spec),
`docs/agent-memory-design.md` (§11 Auth/Isolation, §12 Deployment Topology),
`docs/operations.md` (§1.1, §3 Secrets, §4 SASL/TLS, §8 Security, §11 compose).

---

## 1. Goal

Make the Simple Agent production compose participate in the RAG broker-first
memory stack over one **shared private Docker network** (`rag-memory-test`) and
one **shared Redpanda broker** (internal listener `redpanda-rag-local:19092`),
so that:

- conversation-server publishes `domain.memory.commands` and consumes
  `domain.memory.results` (session recording, compression, lookup, profile ops)
  against the RAG `memory_service` exactly as the locked memory contract defines;
- identity-server publishes `identity.user.events` consumed by `memory_service`
  for profile basic-info enrichment;
- both sides sign/verify with **one shared HS256 signing key**
  (`SERVICE_AUTH_SIGNING_KEY` == SA's `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY`),
  issuer `simple-agent-local`, audience `simple-agent-internal`, TTL `300`;
- production and local run the **same service topology and code paths** — only
  addresses/credentials/ports/paths differ via config (structure.md golden rule).

The memory stack stays **private**: no public ingress to Redpanda, Qdrant, or
memory_service; the only public surface remains Simple Agent's gateway/web.

---

## 2. Shared network and ownership

| Item | Value | Owner |
| --- | --- | --- |
| Shared network name | `rag-memory-test` (bridge, private) | **RAG creates it** |
| Broker internal listener | `redpanda-rag-local:19092` | RAG (Redpanda) |
| Broker dev PLAINTEXT listener | `127.0.0.1:9092` (local-dev only) | RAG |
| Qdrant | `qdrant-rag-local:6333/6334` (or compose service `qdrant`) | RAG |

**Ownership rule.** RAG owns the network and the broker/Qdrant containers. The
Simple Agent compose **declares `rag-memory-test` as `external: true`** (and
`name: rag-memory-test`), never creates it.

- **Local:** `examples/local/run-all.sh --memory` creates `rag-memory-test` via
  `docker network create` and attaches Redpanda with the INTERNAL listener
  advertised as `redpanda-rag-local:19092` (already implemented, C2).
- **Production (RAG compose, `deployment/docker-compose.prod.yml`):** must
  create `rag-memory-test` and attach Redpanda to it with the INTERNAL listener
  advertised at `redpanda-rag-local:19092`. Today the RAG prod compose still
  runs a single `rag-internal` network with broker host `redpanda:19092`; the
  target is the shared network + the `redpanda-rag-local` alias (see §5, §8).

**Security constraints on the shared network:**

1. Never host-publish the INTERNAL listener on a public interface. The RAG prod
   compose currently maps `19092:19092`; this must be removed or bound to
   loopback in production. The `127.0.0.1:9092` PLAINTEXT listener stays
   host-local and dev-only.
2. SASL/TLS may stay commented (private-network trust) — but if enabled on the
   internal listener, **every** memory-path client (RAG workers **and** SA
   conversation-server/identity-server) must present the same credentials.
3. No public ingress/LB to Redpanda, Qdrant, Redis, or `memory_service`.

---

## 3. Simple Agent services that join the shared network

Exactly three SA services join `rag-memory-test`. Each also keeps its existing
`backend` (internal) network membership.

| SA service | Why it joins | Env to add | Networks |
| --- | --- | --- | --- |
| `conversation-server-worker` | Runs the provider saga + `MemoryBrokerClient` (broker mode): publishes `domain.memory.commands`, awaits `domain.memory.results`; also consumes the SA-internal `helper.conversation.commands.v1` on the same broker | `REDPANDA_BOOTSTRAP_SERVERS: redpanda-rag-local:19092` | `[backend, rag-memory-test]` |
| `conversation-server-api` | Production/local parity (same code path; `memory.client_mode: broker` is service-wide). Safe no-op today, ready when the api runs the saga | `REDPANDA_BOOTSTRAP_SERVERS: redpanda-rag-local:19092` | `[backend, rag-memory-test]` |
| `identity-server-worker` | Publishes `identity.user.events` (sole publisher) | `REDPANDA_BOOTSTRAP_SERVERS: redpanda-rag-local:19092`, `REDPANDA_ENABLED: "true"` | `[backend, rag-memory-test]` |

**No other SA service** (gateway, agent, provider, usage, audit, web) joins the
shared network or needs any broker env. Qdrant/Redis/memory_service are never
reached from SA except through the broker.

Flags/env each SA service already has (committed, no change):

- `configs/conversation-server/production.yaml`: `memory.client_mode: broker`,
  `command_topic: domain.memory.commands`, `result_topic: domain.memory.results`,
  `bootstrap_servers_env: REDPANDA_BOOTSTRAP_SERVERS`.
- `configs/identity-server/production.yaml`: `redpanda.enabled: true`,
  `event_topic: identity.user.events`,
  `bootstrap_servers_env: REDPANDA_BOOTSTRAP_SERVERS`.
- `SERVICE_AUTH_SIGNING_KEY` (from `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY`),
  `SERVICE_AUTH_TOKEN_ISSUER`, `SERVICE_AUTH_TOKEN_AUDIENCE`,
  `SERVICE_AUTH_TOKEN_TTL_SECONDS` — all already injected via the compose
  `x-service-auth` anchor into every service.

> **`SERVICE_AUTH_ALLOWED_SERVICES` is NOT a memory-path flag.** It gates inbound
> SA-internal HTTP service-auth and is already set per service
> (e.g. conversation-server: `gateway-server,task-executor-server`). No change
> is required for the memory integration. The memory path's inbound allow-list
> lives on the RAG side as `MEMORY_ALLOWED_SERVICES` (must include
> `conversation-server`).

---

## 4. RAG-side prerequisites (target state)

The RAG production compose must expose the memory path on the shared network so
SA can reach it (see `docs/operations.md` §1.1 key-env block):

| RAG setting | Target value |
| --- | --- |
| `BROKER_BOOTSTRAP_SERVERS` (memory/retrieval workers) | `redpanda-rag-local:19092` |
| `BROKER_TOPIC_PREFIX` | `""` (bare topics shared with SA) |
| `MEMORY_IDENTITY_MODE` / `MEMORY_INDEX_MODE` / `MEMORY_SEARCH_MODE` | `broker` |
| `MEMORY_ALLOWED_SERVICES` | includes `conversation-server` |
| `SERVICE_AUTH_SIGNING_KEY` | **equal** to SA's `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY` |
| `SERVICE_AUTH_TOKEN_ISSUER` | `simple-agent-local` |
| `SERVICE_AUTH_TOKEN_AUDIENCE` | `simple-agent-internal` |
| `SERVICE_AUTH_TOKEN_TTL_SECONDS` | `300` |
| Redpanda INTERNAL listener | advertised `redpanda-rag-local:19092`, on `rag-memory-test`, **not** host-published publicly |

---

## 5. Required config changes (the deltas)

### 5.1 Simple Agent (Dev SA #12)

1. **`infra/docker/compose.production.yaml`** — add the shared network and wire
   the three services (mirrors `compose.local.yaml` which already has this
   pattern):
   ```yaml
   networks:
     backend:
       internal: true
     egress:
     rag-memory-test:
       external: true
       name: rag-memory-test
   ```
   - `conversation-server-api` and `conversation-server-worker`:
     `networks: [backend, rag-memory-test]` +
     `REDPANDA_BOOTSTRAP_SERVERS: redpanda-rag-local:19092`.
   - `identity-server-worker`:
     `networks: [backend, rag-memory-test]` +
     `REDPANDA_BOOTSTRAP_SERVERS: redpanda-rag-local:19092` +
     `REDPANDA_ENABLED: "true"`.
2. **Issuer alignment (blocking).** The `x-service-auth` anchor currently sets
   `SERVICE_AUTH_TOKEN_ISSUER: simple-agent-production`. The memory contract
   (operations.md §3.1, RAG `configs/production.env.example`, RAG compose
   default, `shared/service_auth.py` default, and the SA local compose) all use
   `simple-agent-local`. `memory_service` **rejects any token whose `iss` is not
   its configured issuer** (`verify_service_token`), so with the current value
   every memory command 401s. Change the anchor to
   `SERVICE_AUTH_TOKEN_ISSUER: simple-agent-local`. Safe: all SA services share
   the same anchor, so mint and verify sides move together; production then
   matches local.

### 5.2 RAG (Dev RAG #11)

1. Create/declare `rag-memory-test` and attach Redpanda with the INTERNAL
   listener advertised as `redpanda-rag-local:19092` (network alias or service
   rename so that hostname resolves on the shared network).
2. Point the memory-path broker env at `redpanda-rag-local:19092` (keep
   `BROKER_TOPIC_PREFIX=""`).
3. Remove the public host publish of the internal listener (`19092:19092`),
   or bind it to loopback for local-dev parity.
4. Keep `SERVICE_AUTH_TOKEN_ISSUER=simple-agent-local` (the compose default is
   already this; do **not** override to `simple-agent-production`).

### 5.3 Shared secret

`SERVICE_AUTH_SIGNING_KEY` (RAG) and `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY`
(SA) must hold the **same value**. Set via a secret manager in production; never
commit. `memory_service` fails fast at startup (B3 guard) when broker modes are
set and the key is missing/empty/whitespace. Drift produces `401`/`403` on every
memory command, not a startup error.

---

## 6. Contract table

### 6.1 Topics (bare names; `BROKER_TOPIC_PREFIX=""` on both sides)

| Topic | Producer | Consumer(s) | Consumer group(s) | Envelope / auth |
| --- | --- | --- | --- | --- |
| `domain.memory.commands` | SA conversation-server (`MemoryBrokerClient`) | RAG `memory_service` | `memory_service` | `DOMAIN_COMMAND`, data_type `agent_memory`, schema v1; HS256 service token in headers (`svc=conversation-server`, actor claims) |
| `domain.memory.results` | RAG `memory_service` | SA conversation-server (`MemoryBrokerClient`) | `conversation-server.memory-client.<hex>` (unique per instance) | `DOMAIN_RESULT`, reply key = `task_id`; caller matches by `correlation_id` + `operation` |
| `identity.user.events` | SA identity-server (`RedpandaIdentityEventPublisher`, sole publisher) | RAG `memory_service` | `memory_service.identity` | **Raw, no service token** (private-network trust). Keyed by `owner_user_id`. Only `identity.user.registered` / `identity.user.status_changed` applied; backfilled ignored |
| `helper.retrieval_index.commands` | RAG `memory_service` (hand-off) | RAG retrieval index worker | `retrieval_service` | RAG-internal (SA does not touch) |
| `helper.retrieval.commands` | RAG `memory_service` (hand-off) | RAG retrieval helper worker | — | RAG-internal |
| `helper.retrieval.results` | RAG retrieval helper worker | RAG `memory_service` | `memory_service.retrieval` | RAG-internal |
| `helper.conversation.commands.v1` | SA (api/saga) | SA conversation-server-worker | `conversation-server` | SA-internal, but lives on the **same broker** — no rename |

### 6.2 Environment keys

| Key | Value (production) | Set by | Consumed by |
| --- | --- | --- | --- |
| `REDPANDA_BOOTSTRAP_SERVERS` | `redpanda-rag-local:19092` | SA compose (3 services) | conversation-server (api + worker), identity-server-worker |
| `REDPANDA_ENABLED` | `"true"` | SA compose | identity-server-worker (`redpanda.enabled` override) |
| `memory.client_mode` | `broker` | SA `production.yaml` (committed) | conversation-server |
| `BROKER_BOOTSTRAP_SERVERS` | `redpanda-rag-local:19092` | RAG compose | RAG memory/retrieval workers |
| `BROKER_TOPIC_PREFIX` | `""` | RAG compose | RAG workers |
| `MEMORY_ALLOWED_SERVICES` | `conversation-server` | RAG compose | RAG `memory_service` (token `svc` allow-list) |
| `SERVICE_AUTH_SIGNING_KEY` | = `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY` | RAG compose + SA compose (`x-service-auth`) | RAG `memory_service` verify; SA token mint |
| `SERVICE_AUTH_TOKEN_ISSUER` | `simple-agent-local` | both composes | SA mint; RAG verify |
| `SERVICE_AUTH_TOKEN_AUDIENCE` | `simple-agent-internal` | both composes | SA mint; RAG verify |
| `SERVICE_AUTH_TOKEN_TTL_SECONDS` | `300` | both composes | SA mint; RAG verify |

### 6.3 Secrets (never committed; env or `*_FILE`)

| Secret | Shared? | Notes |
| --- | --- | --- |
| `SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY` / `SERVICE_AUTH_SIGNING_KEY` | **Yes — one value both repos** | The whole memory surface authenticates with this single HS256 key. `*_FILE` supported on the RAG config layer. |
| `BROKER_SASL_PLAIN_PASSWORD` (+ username) | Yes, if SASL enabled | Shared across RAG workers and SA conversation/identity clients; currently commented (private-network trust). |
| `REDIS_PASSWORD` | RAG-only | SA never touches RAG Redis. |

### 6.4 Issuer / audience / TTL (single contract)

| Field | Value |
| --- | --- |
| issuer (`iss`) | `simple-agent-local` |
| audience (`aud`) | `simple-agent-internal` |
| TTL | `300` s |

---

## 7. Auth model (what the wiring must preserve)

- **Service tokens.** conversation-server mints an HS256 token per request with
  `create_service_token` (claims: `iss`, `aud`, `svc=conversation-server`,
  `actor_user_id`, `actor_role`, `iat`, `exp`). `memory_service` verifies it with
  the mirrored `shared/service_auth.verify_service_token`: HMAC signature, `alg`
  HS256 / `typ` SA-SERVICE, `iss == configured issuer`, `aud == configured
  audience`, `exp-iat <= TTL`, `svc in MEMORY_ALLOWED_SERVICES`, actor claims
  valid. `actor_user_id` → `owner_user_id`; `X-Actor-User-ID` must match the
  token; `X-Agent-ID` present (payload-compared for agent-scoped ops).
- **Identity events are raw (no token).** Sole publisher is identity-server on
  the private broker; `memory_service` consumes under the private-network trust
  boundary. **Do not add identity-event signing.**
- **One verifier contract.** RAG `shared/service_auth.py` is a dependency-free
  mirror of `simple_agent_service_auth`; both must stay in lockstep (algorithm,
  header, claims, local-dev defaults).

---

## 8. Verify / acceptance criteria

Every criterion below is runnable. Items marked (SA) / (RAG) run in that repo;
(**E2E**) needs both stacks up.

1. **(SA)** `docker compose -f infra/docker/compose.production.yaml config`
   (with dummy secrets) shows: `rag-memory-test` declared `external: true`;
   conversation-server-api/worker and identity-server-worker on
   `[backend, rag-memory-test]` with `REDPANDA_BOOTSTRAP_SERVERS:
   redpanda-rag-local:19092`; identity-server-worker also
   `REDPANDA_ENABLED: "true"`; `SERVICE_AUTH_TOKEN_ISSUER: simple-agent-local`
   in `x-service-auth`.
2. **(SA)** `tests/phase18/conversation/test_memory_broker_client.py` and
   `tests/phase18/identity/test_redpanda_identity_publisher.py` pass (currently
   35 passing).
3. **(RAG)** `tests/memory/` passes (currently 52 passing), including the B3
   guard (broker modes + missing signing key fail fast).
4. **(RAG)** `deployment/docker-compose.prod.yml config` is valid with dummy
   secrets; Redpanda advertises `INTERNAL://redpanda-rag-local:19092`; the
   internal listener is not host-published publicly; memory/retrieval workers
   use `BROKER_BOOTSTRAP_SERVERS=redpanda-rag-local:19092`.
5. **(RAG)** `docker network ls` shows `rag-memory-test` after bring-up; both
   the RAG stack and the SA stack attach to it (verified via
   `docker network inspect rag-memory-test`).
6. **(E2E)** From the SA `conversation-server-worker` container,
   `redpanda-rag-local:19092` resolves and connects (broker reachability);
   `domain.memory.commands`, `domain.memory.results`, `identity.user.events`
   exist with the canonical settings.
7. **(E2E)** Register a fresh user → identity-server publishes
   `identity.user.registered` (keyed by `owner_user_id`) → `memory_service`
   consumes (group `memory_service.identity`) → a `user_profiles` row is created
   (AC-9).
8. **(E2E)** Drive a chat → `session.start`/`message.record` land as
   `sessions`/`messages` rows with the shared signing key; `memory.lookup`
   returns per-source results including `chat_history` and (when present) facts
   (AC-1/2/7). A token minted with the SA production settings verifies in the
   RAG `verify_service_token` path with `svc=conversation-server`.
9. **(E2E)** Corrupt the key on one side only → every memory command returns
   `401`/`403` (proves drift detection), and chat **survives** (lookup is
   best-effort).
10. **(Security)** No `*:19092`, `*:6333`, or `*:6334` published on a public
    interface by either compose.

---

## 9. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Issuer drift (`simple-agent-production` vs `simple-agent-local`) — was present; both composes now use `simple-agent-local` | Every memory command 401s if reintroduced | Kept the same value on both `x-service-auth` and the RAG memory default; acceptance #1/#8 prove it. |
| Signing-key drift between repos | Silent `401`/`403` on every memory command | One shared secret set by the operator; B3 guard catches missing/empty keys at startup; acceptance #9 proves drift detection. |
| RAG prod compose still on `rag-internal`/`redpanda:19092` | SA cannot reach the broker on `redpanda-rag-local:19092`; two topologies drift from local | Dev RAG #11 migrates to `rag-memory-test` + `redpanda-rag-local:19092`; acceptance #3/#4/#5. |
| Internal listener host-published (`19092:19092` in RAG prod compose today) | Exposes the memory broker beyond the private boundary | Remove/bind-to-loopback; acceptance #10. |
| SASL/TLS enabled on only one side | Broker auth failures in worker logs | If SASL is enabled, both RAG and SA clients present the same credentials; keep commented until verified (`examples/local/verify-sasl.sh`). |
| Redis password / SASL password committed | Secret leak | Secrets come from env/`*_FILE`/secret manager only; `.dockerignore` excludes `*.env`/certs; acceptance is the compose diff, not a secret in-repo. |
| identity-event forgery if the broker is ever exposed | Profile poisoning | Events are raw only under the private-network trust boundary; if the broker is ever exposed beyond the private network, identity-event signing becomes **required** (declared follow-up). |
| SA conversation-server-worker starts a `MemoryBrokerClient` before broker topics exist | `unavailable`/timeout on first memory op; chat survives | Broker topics are bootstrapped by the RAG stack (`bootstrap_topics`); chat is fire-and-forget/best-effort by design. |

---

## 10. Out of scope (this wiring)

- SA `ingest_documents` client (documents reachable only out-of-band today; FR-3.1 decision).
- Identity-event signing, model-backed summarization, retention/TTL, `history.replay`.
- SA-internal broker topics (`helper.conversation.commands.v1`) beyond noting they share the broker.

Reference files: `docs/operations.md`, `docs/agent-memory-requirements.md`,
`examples/local/run-all.sh` (network/listener creation), SA
`infra/docker/compose.production.yaml`, SA
`configs/conversation-server/production.yaml`, SA
`configs/identity-server/production.yaml`,
`deployment/docker-compose.prod.yml`, `configs/production.env.example`.
