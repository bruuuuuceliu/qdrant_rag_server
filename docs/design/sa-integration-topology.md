# SA <-> RAG Shared-Network Topology (production compose wiring)

Status: design. Scope: production Docker Compose wiring that connects Simple Agent
(`simple_agent`) conversation/identity services to the RAG memory path over a shared
private broker network. The working reference is Connection B3 already wired in
`simple_agent/infra/docker/compose.local.yaml` and reproduced here for production.

The golden rule (structure.md) is satisfied because production uses the **same
service topology and code paths** as `examples/local/run-all.sh --memory`; only
addresses, credentials, ports, and paths differ via config.

---

## (a) Network ownership rule

| Repo | Declaration | Role |
| --- | --- | --- |
| **qdrant_rag_server** | `rag-memory-test:` non-external, with explicit `name: rag-memory-test` | **Creates** the network (owns the global name). `internal: true` (no default route). |
| **simple_agent** | `rag-memory-test: external: true` | **Joins only.** Must already exist before `up` (bring the RAG stack up first, or pre-create it). |

Why RAG creates it: this mirrors local, where `examples/local/run-all.sh`
`ensure_redpanda_on_memory_network` / `start_redpanda_if_needed` run
`docker network create rag-memory-test` and attach Redpanda. SA local compose
already declares it `external: true`; production must too. The exact name is set
via `name: rag-memory-test` in the RAG compose because the RAG project
(`name: qdrant-rag`) would otherwise prefix it (`qdrant-rag_rag-memory-test`),
which SA's external declaration could not resolve.

Bring-up order is therefore: **RAG production compose up** (creates the network
and the broker), then **SA production compose up**. The network is idempotent:
compose reuses it if it already exists.

---

## (b) Attaching RAG's Redpanda to the shared network

Redpanda joins **both** networks:

- `rag-internal` — the RAG container mesh (workers, qdrant, redis, prometheus).
- `rag-memory-test` — the shared memory path.

On each network it carries the explicit service alias **`redpanda-rag-local`** so
that any container on either network resolves `redpanda-rag-local:19092` to the
broker (compose's default alias is the service name `redpanda`; the alias is what
SA's config points at). SA services on `rag-memory-test` therefore resolve
`redpanda-rag-local:19092` exactly as they do locally.

The alias on `rag-internal` matters because the INTERNAL listener now advertises
`redpanda-rag-local:19092`; every RAG worker uses that bootstrap value and must be
able to resolve it from `rag-internal` (see (c)).

---

## (c) Redpanda listeners / addresses

| Listener | Bind | Advertise | Reachable from | Production use |
| --- | --- | --- | --- | --- |
| `PLAINTEXT` | `0.0.0.0:9092` | `localhost:9092` | host loopback (`127.0.0.1:9092` mapping) and both private networks | **Dev-only convenience.** Kept in the command for command-shape parity with `run-all.sh`; host publish is bound to `127.0.0.1`. Never on a public interface. |
| `INTERNAL` | `0.0.0.0:19092` | **`redpanda-rag-local:19092`** (changed from `redpanda:19092`) | containers on `rag-internal` + `rag-memory-test` | **The production listener.** `BROKER_BOOTSTRAP_SERVERS=redpanda-rag-local:19092` everywhere. **Not host-published at all** (constraint: no public exposure of the internal listener). |

Decisions:

1. The advertise address **changes** from `INTERNAL://redpanda:19092` to
   `INTERNAL://redpanda-rag-local:19092` so it matches the local contract
   (`run-all.sh --memory`: `INTERNAL://redpanda-rag-local:19092`) and SA's config.
2. **Keep** the PLAINTEXT `9092` listener in the command (parity with local, and a
   host-local dev escape hatch), but publish it **host-local only**
   (`127.0.0.1:9092:9092`). Its production use is nil — every production client
   uses the INTERNAL listener.
3. The `19092` host mapping is **removed** (no host publish). SA reaches it over
   the Docker network, not the host. The `9644` admin API is host-local only
   (`127.0.0.1:9644:9644`).

Note (single-host shape): both listeners are bound to `0.0.0.0` inside the
container, so both are technically reachable on every network the container
joins. The security boundary is the private networks themselves plus the
host-local port binds; SASL/TLS on the INTERNAL listener is the documented
hardening when the broker must be carried beyond a private host/VPC
(operations.md §4, design §12.4).

---

## (d) Simple Agent services on the shared network

| SA service | Joins `rag-memory-test` | New env | Notes |
| --- | --- | --- | --- |
| `conversation-server-api` | yes (`[backend, rag-memory-test]`) | `REDPANDA_BOOTSTRAP_SERVERS=redpanda-rag-local:19092` | Publishes `domain.memory.commands`; mints service tokens. `memory.client_mode: broker` is baked into the image config (`configs/conversation-server/production.yaml`). |
| `conversation-server-worker` | yes (`[backend, rag-memory-test]`) | `REDPANDA_BOOTSTRAP_SERVERS=redpanda-rag-local:19092` | Same as API. |
| `identity-server-worker` | yes (`[backend, rag-memory-test]`) | `REDPANDA_BOOTSTRAP_SERVERS=redpanda-rag-local:19092`, `REDPANDA_ENABLED: "true"` | Publishes `identity.user.events` (sole publisher). `redpanda.enabled: true` is already baked into `configs/identity-server/production.yaml`, so the compose `REDPANDA_ENABLED="true"` is **explicit-but-redundant** — kept to mirror the spec contract and the local compose, and to fail loudly if the config default ever flips. |
| `identity-server-api` | no | — | Does not touch the broker; unchanged. |

No SA service needs a direct qdrant/redis/memory_service address: the memory path
is **broker-only** (no SA<->RAG HTTP calls; design §12.1). SA joins the shared
network solely to reach `redpanda-rag-local:19092`.

---

## (e) Secret flow (env interpolation, never committed)

| Secret | SA side | RAG side | Notes |
| --- | --- | --- | --- |
| `SERVICE_AUTH_SIGNING_KEY` (SHARED) | `${SIMPLE_AGENT_SERVICE_AUTH_SIGNING_KEY:?...}` injected as `SERVICE_AUTH_SIGNING_KEY` by the `x-service-auth` anchor (already present) | `${SERVICE_AUTH_SIGNING_KEY:?...}` on the `memory` service (already present) | **Same value both sides** (single contract, operations.md §3.1). Drift -> every token 401/403. |
| `SERVICE_AUTH_TOKEN_ISSUER` | `simple-agent-local` (`x-service-auth` anchor) | memory default `simple-agent-local` (same) | `simple-agent-local` / `simple-agent-internal` / `300` on **both** composes and local `run-all.sh --memory` (single contract, operations.md §3.1). |
| `REDIS_PASSWORD` | — | `${REDIS_PASSWORD:?}` on the RAG `redis` service and `x-rag-env` | RAG-only (its own Redis on `rag-internal`). SA has its own Redis on `backend`; the memory path does **not** share Redis. |
| SASL (if enabled) | `BROKER_SECURITY_PROTOCOL`, `BROKER_SASL_MECHANISM`, `BROKER_SASL_PLAIN_USERNAME`, `BROKER_SASL_PLAIN_PASSWORD` read by `memory_client` env-wins | same `BROKER_*` env in `x-rag-env` (currently commented) | Same credentials on every memory-path client (RAG workers + SA conversation/identity). Default here stays PLAINTEXT under private-network trust; uncomment symmetrically to enable. |

All values come from the deployment environment (`docker compose ... up` env or a
`.env`) or `<KEY>_FILE` mounts; never committed.

---

## (f) Health-check strategy

| Layer | Mechanism |
| --- | --- |
| Broker | Redpanda healthcheck unchanged (`curl :9644/v1/status/ready`). |
| RAG memory path | `memory` (`:9012`), `retrieval` (`:9007`), `retrieval-index` (`:9008`) keep their existing ops `/readyz` healthchecks. |
| SA API | `conversation-server-api` keeps `*api-healthcheck` (`/health/ready` on `SERVICE_PORT`). Its readiness does not hard-fail on broker outage (saga best-effort; operations.md §7.1). |
| SA workers | `conversation-server-worker` / `identity-server-worker` have no HTTP surface and no healthcheck — consistent with the existing worker pattern. Their health is observed via broker consumer-group attachment + logs, and end-to-end via the readiness report. |
| End-to-end | RAG `python -m deployment.composition.readiness` (broker/redis/storage/sqlite/qdrant + memory/retrieval) plus SA `conversation-server-api /health/ready`. |

---

## (g) Compose fragments

### RAG — `qdrant_rag_server/deployment/docker-compose.prod.yml`

(1) `networks:` block — add the shared network:

```yaml
networks:
  # Normal bridge so workers can reach S3/OpenRouter/HuggingFace when enabled.
  # Harden at the host/cloud firewall; the RAG stack is never publicly exposed.
  rag-internal:
  # Shared memory-path trust network. RAG CREATES it; simple_agent's compose
  # declares it `external: true` and only joins. The exact global name is set
  # with `name:` so the qdrant-rag project does not prefix it. internal:true
  # removes the default route (members egress via their other networks). SA can
  # reach ONLY this network -- never place qdrant/redis/worker ops on it.
  rag-memory-test:
    name: rag-memory-test
    internal: true
```

(2) `x-rag-env` anchor — point every worker at the production INTERNAL listener:

```yaml
  # Broker: INTERNAL listener on the private shared network (bare topics so the
  # simple_agent memory path shares names). Same contract as
  # examples/local/run-all.sh --memory (redpanda-rag-local:19092); production
  # clients reach the internal listener only (operations.md §1.1).
  BROKER_BOOTSTRAP_SERVERS: redpanda-rag-local:19092
  BROKER_TOPIC_PREFIX: "${BROKER_TOPIC_PREFIX:-}"
```

(3) `redpanda` service — advertise + network membership + host-local ports:

```yaml
  redpanda:
    image: docker.redpanda.com/redpandadata/redpanda:${REDPANDA_TAG:-latest}
    command: >
      redpanda start --overprovisioned --smp 1 --memory 1G --reserve-memory 0M
      --node-id 0 --check=false
      --kafka-addr PLAINTEXT://0.0.0.0:9092,INTERNAL://0.0.0.0:19092
      --advertise-kafka-addr PLAINTEXT://localhost:9092,INTERNAL://redpanda-rag-local:19092
      --rpc-addr 0.0.0.0:33145 --advertise-rpc-addr redpanda:33145
    ports:
      - "127.0.0.1:9092:9092"   # PLAINTEXT dev listener -- host-local ONLY
      - "127.0.0.1:9644:9644"   # admin API -- host-local only
      # 19092 (INTERNAL listener) is NOT host-published: reachable only by
      # containers on rag-internal / rag-memory-test (never a public interface).
    networks:
      rag-internal:
        aliases:
          - redpanda-rag-local
      rag-memory-test:
        aliases:
          - redpanda-rag-local
    volumes:
      - redpanda-data:/var/lib/redpanda/data
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:9644/v1/status/ready || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 30
      start_period: 15s
```

(4) `memory` service — issuer parity + join the shared network (the only other
changes are its `networks:` list and the issuer default; everything else stays):

```yaml
  memory:
    <<: *rag-service
    command: ["python", "-m", "memory_service.worker"]
    environment:
      <<: *rag-env
      RAG_OPS_PORT: "9012"
      MEMORY_DB_PATH: /var/lib/rag/agent_memory.db
      MEMORY_IDENTITY_MODE: broker
      MEMORY_INDEX_MODE: broker
      MEMORY_SEARCH_MODE: broker
      MEMORY_ALLOWED_SERVICES: ${MEMORY_ALLOWED_SERVICES:-conversation-server}
      MEMORY_COLLECTION: ${MEMORY_COLLECTION:-agent_memory}
      MEMORY_DOCUMENTS_COLLECTION: ${MEMORY_DOCUMENTS_COLLECTION:-agent_documents}
      # Single signing-key contract with simple_agent (operations.md §3.1).
      SERVICE_AUTH_SIGNING_KEY: "${SERVICE_AUTH_SIGNING_KEY:?SERVICE_AUTH_SIGNING_KEY is required}"
      # Issuer MUST equal simple_agent's x-service-auth issuer (simple-agent-local)
      # or every conversation-server token fails iss verification (§7.1).
      SERVICE_AUTH_TOKEN_ISSUER: ${SERVICE_AUTH_TOKEN_ISSUER:-simple-agent-local}
      SERVICE_AUTH_TOKEN_AUDIENCE: ${SERVICE_AUTH_TOKEN_AUDIENCE:-simple-agent-internal}
      SERVICE_AUTH_TOKEN_TTL_SECONDS: ${SERVICE_AUTH_TOKEN_TTL_SECONDS:-300}
    networks: [rag-internal, rag-memory-test]
    ports: ["127.0.0.1:9012:9012"]
    healthcheck:
      <<: *rag-healthcheck
      test: ["CMD", "curl", "-fsS", "http://localhost:9012/readyz"]
```

(5) `retrieval` and (6) `retrieval-index` — join the shared network (add one line
each; everything else stays):

```yaml
  retrieval:
    <<: *rag-service
    command: ["python", "-m", "retrieval_service.server.worker"]
    environment:
      <<: *rag-env
      RAG_OPS_PORT: "9007"
    networks: [rag-internal, rag-memory-test]
    ports: ["127.0.0.1:9007:9007"]
    healthcheck:
      <<: *rag-healthcheck
      test: ["CMD", "curl", "-fsS", "http://localhost:9007/readyz"]
```

```yaml
  retrieval-index:
    <<: *rag-service
    command: ["python", "-m", "retrieval_service.indexing.worker"]
    environment:
      <<: *rag-env
      RAG_OPS_PORT: "9008"
    networks: [rag-internal, rag-memory-test]
    ports: ["127.0.0.1:9008:9008"]
    healthcheck:
      <<: *rag-healthcheck
      test: ["CMD", "curl", "-fsS", "http://localhost:9008/readyz"]
```

The remaining 10 RAG workers and qdrant/redis/prometheus are untouched except
that qdrant/redis stay on `rag-internal` (SA never reaches them). The smoke
override (`docker-compose.prod.override.smoke.yml`) is unaffected.

### SA — `simple_agent/infra/docker/compose.production.yaml`

(1) `networks:` block — add the external shared network:

```yaml
networks:
  backend:
    internal: true
  egress:
  # Connection B3 parity with compose.local.yaml: rag-memory-test is the PRIVATE
  # shared memory-path network CREATED by the qdrant_rag_server production
  # compose (`name: rag-memory-test`). SA declares it external and only joins --
  # it must exist before `up` (bring the RAG stack up first, or pre-create it).
  # Reachable members: redpanda-rag-local:19092 (Redpanda INTERNAL listener) and
  # the RAG memory/retrieval workers. Never publish anything here publicly.
  rag-memory-test:
    external: true
```

(2) `conversation-server-api` — join + broker env:

```yaml
  conversation-server-api:
    <<: *service-runtime
    image: simple-agent/conversation-server:production
    build:
      context: ../..
      dockerfile: services/conversation-server/Dockerfile
    command: ["api"]
    user: "${SIMPLE_AGENT_RUNTIME_UID:-10001}:${SIMPLE_AGENT_RUNTIME_GID:-10001}"
    environment:
      <<: *service-auth
      SERVICE_PORT: "8050"
      DATABASE_URL: sqlite:////app/data/conversations.db
      SERVICE_IDENTITY: conversation-server
      SERVICE_IDENTITY_TOKEN: "${SIMPLE_AGENT_SERVICE_IDENTITY_TOKEN:?SIMPLE_AGENT_SERVICE_IDENTITY_TOKEN is required}"
      SERVICE_AUTH_ALLOWED_SERVICES: gateway-server,task-executor-server
      AGENT_SERVER_URL: http://agent-server-api:8040
      # Connection B3: redpanda-rag-local:19092 is Redpanda's INTERNAL listener
      # on the private rag-memory-test network only (created by the RAG compose).
      # Never publish it or route it through a public LB/ingress.
      REDPANDA_BOOTSTRAP_SERVERS: redpanda-rag-local:19092
    volumes:
      - conversation-data:/app/data
    networks: [backend, rag-memory-test]
    healthcheck: *api-healthcheck
    depends_on:
      agent-server-api:
        condition: service_healthy
```

(3) `conversation-server-worker` — same join + env (add to its existing
environment/network lists):

```yaml
  conversation-server-worker:
    <<: *service-runtime
    image: simple-agent/conversation-server:production
    build:
      context: ../..
      dockerfile: services/conversation-server/Dockerfile
    command: ["worker"]
    user: "${SIMPLE_AGENT_RUNTIME_UID:-10001}:${SIMPLE_AGENT_RUNTIME_GID:-10001}"
    environment:
      <<: *service-auth
      DATABASE_URL: sqlite:////app/data/conversations.db
      SERVICE_IDENTITY: conversation-server
      SERVICE_IDENTITY_TOKEN: "${SIMPLE_AGENT_SERVICE_IDENTITY_TOKEN:?SIMPLE_AGENT_SERVICE_IDENTITY_TOKEN is required}"
      SERVICE_AUTH_ALLOWED_SERVICES: gateway-server,task-executor-server
      AGENT_SERVER_URL: http://agent-server-api:8040
      AUDIT_SERVER_URL: http://audit-server-api:8060
      # Connection B3: redpanda-rag-local:19092 (private rag-memory-test network).
      REDPANDA_BOOTSTRAP_SERVERS: redpanda-rag-local:19092
    volumes:
      - conversation-data:/app/data
    networks: [backend, rag-memory-test]
    depends_on:
      agent-server-api:
        condition: service_healthy
      audit-server-api:
        condition: service_healthy
```

(4) `identity-server-worker` — join + broker env:

```yaml
  identity-server-worker:
    <<: *service-runtime
    image: simple-agent/identity-server:production
    build:
      context: ../..
      dockerfile: services/identity-server/Dockerfile
    command: ["worker"]
    user: "${SIMPLE_AGENT_RUNTIME_UID:-10001}:${SIMPLE_AGENT_RUNTIME_GID:-10001}"
    environment:
      <<: *service-auth
      DATABASE_URL: sqlite:////app/data/identity.db
      REDIS_URL: redis://redis:6379/0
      SERVICE_IDENTITY: identity-server
      SERVICE_IDENTITY_TOKEN: "${SIMPLE_AGENT_SERVICE_IDENTITY_TOKEN:?SIMPLE_AGENT_SERVICE_IDENTITY_TOKEN is required}"
      SERVICE_AUTH_ALLOWED_SERVICES: gateway-server
      USAGE_SERVER_URL: http://usage-server-api:8080
      # Connection B3: publish identity.user.events to the shared broker.
      REDPANDA_BOOTSTRAP_SERVERS: redpanda-rag-local:19092
      # Explicit-but-redundant: production.yaml config already sets
      # redpanda.enabled: true (baked into the image). Kept to mirror the spec
      # contract and compose.local.yaml, and to fail loudly if the config default
      # ever flips. (In compose.local.yaml it IS required -- the local config
      # default is disabled.)
      REDPANDA_ENABLED: "true"
    volumes:
      - identity-data:/app/data
    networks: [backend, rag-memory-test]
    depends_on:
      redis:
        condition: service_healthy
      usage-server-api:
        condition: service_healthy
```

No other SA service changes.

### Deployment posture (applied in `docker-compose.prod.yml`)

The memory-path ports are **already bound host-local** in the production compose
(the review closed the all-interfaces exposure):

- `qdrant` — `127.0.0.1:6333/6334` (vector data path, never public).
- Every RAG worker ops port (`9001`-`9012`) — `127.0.0.1` (they expose only
  `/healthz` `/readyz` `/metrics`).
- `redpanda` — `127.0.0.1:9092/9644` host-local; the `19092` INTERNAL listener is
  **not** host-published (private network only). Host-local access for interop is
  opt-in via `docker-compose.prod.override.interop.yml` (`127.0.0.1:19092`).
- `manager` — `50051` stays published (the public gRPC API); `9001` ops is
  host-local.
- `prometheus` — `127.0.0.1:9090`.

### Follow-up: SA broker-security helper dedup (non-blocking)

`_kafka_security_kwargs` / `_security_value` / `_security_secret` are duplicated
across `memory_client.py` and `redpanda_identity_publisher.py` (a deliberate SA
mirror of RAG's `broker_service`; no cross-repo imports). Both copies are
currently identical (each honors `{ENV}_FILE` secret injection). To dedup later,
extract into a small `libs/broker-util` and add it to each service Dockerfile's
`COPY` + `PYTHONPATH` (same pattern as `libs/service-auth`). Kept as a follow-up
because it touches build wiring that cannot be validated without rebuilding the
SA service images.

---

## (h) Keep `rag-internal` OR rename it to the shared network?

**Keep both.** Add `rag-memory-test` alongside `rag-internal`.

Rationale:

1. **Minimal churn.** Renaming `rag-internal` to `rag-memory-test` would touch
   every one of the 12 worker service `networks:` entries, the anchors, and the
   smoke override. The additive block changes the `x-rag-env` anchor, the
   `redpanda` service, the `networks:` block, and 3 memory-path services.
2. **Narrower SA trust surface (security).** SA joins **only** `rag-memory-test`.
   On it SA can reach only Redpanda's internal listener (`redpanda-rag-local:19092`)
   and the RAG memory/retrieval workers. `qdrant:6333`, `redis:6379`, and the 12
   worker ops ports stay on `rag-internal`, which SA cannot see. A single shared
   network carrying everything would hand SA reach to the entire RAG surface —
   a security regression against the auth-boundary principle (network isolation).
3. **Parity.** Local already has this exact shape: the RAG container mesh plus a
   distinct private `rag-memory-test` network that only the memory path joins.
   Production mirrors it. Redpanda spanning both is cheap and intentional: it is
   the one shared component (the broker), and the `redpanda-rag-local` alias on
   `rag-internal` keeps the non-memory RAG workers on the same listener contract.
4. **Future-proofing.** If the RAG mesh is ever split onto a private VPC vs. the
   shared memory network, the memory-path workers are already on the right
   network and nothing needs to move.

The one shared component is the broker. Everything else on the memory path
(memory_service, retrieval workers, qdrant, redis) lives on `rag-internal`
(RAG-only) or both, and SA's only view into the memory path is Redpanda's
INTERNAL listener.

---

## Verification notes

- RAG compose parses with the shared-network fragment applied (validated with
  `docker compose -f <merged> config` in a scratch copy; see task notes).
- SA compose parses with the three service changes applied (validated the same
  way with required secret env supplied).
- Live interop is covered by the existing test suites (SA `tests/phase18/...`
  broker-client tests and RAG live-infra/smoke); this doc changes only compose
  wiring, not code paths.
