#!/usr/bin/env bash
# Verify the RAG + simple_agent broker clients connect over SASL_SSL to a
# THROWAWAY Redpanda container (never the live redpanda-rag-local).
#
# Flow:
#   1. Generate a self-signed CA + server cert under .run/sasl-certs/ with the
#      SAN the clients rely on (DNS:localhost, DNS:redpanda-rag-local,
#      IP:127.0.0.1).
#   2. Start a throwaway `redpanda-rag-sasl` container on 127.0.0.1:19093 with a
#      redpanda.yaml that enables a per-listener `authentication_method: sasl`
#      plus `kafka_api_tls`, `kafka_sasl_mechanisms: [SCRAM-SHA-256]`, and the
#      `admin` superuser.
#   3. Bootstrap the SCRAM superuser via the Admin API.
#   4. Prove RAG (tests/integration/test_sasl_live.py) and SA
#      (MemoryBrokerClient + RedpandaIdentityEventPublisher) clients connect
#      over SASL_SSL.
#   5. Tear the throwaway container down.
#
# The live stack stays on PLAINTEXT and is never touched.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SA_ROOT="${SA_ROOT:-$(cd "${ROOT_DIR}/../simple_agent" && pwd)}"
RUNTIME_DIR="${RAG_LOCAL_RUNTIME_DIR:-${ROOT_DIR}/.run}"
CERT_DIR="${RUNTIME_DIR}/sasl-certs"
CONTAINER="redpanda-rag-sasl"
KAFKA_HOST="127.0.0.1"
KAFKA_PORT="19093"
ADMIN_PORT="19644"
SASL_PASSWORD="verify-sasl-secret"
SASL_USER="admin"
SASL_MECHANISM="SCRAM-SHA-256"
PYTHON_BIN="${PYTHON_BIN:-python}"

cleanup() {
  echo "--- teardown ---"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required to run SASL verification." >&2
  exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate the self-signed certs." >&2
  exit 1
fi

mkdir -p "$CERT_DIR"

echo "=== 1. Generating self-signed CA + server cert under ${CERT_DIR} ==="
rm -f "$CERT_DIR"/*.crt "$CERT_DIR"/*.key "$CERT_DIR"/*.srl "$CERT_DIR"/*.csr
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt" \
  -days 2 -subj "/CN=verify-sasl-ca" 2>/dev/null
openssl req -newkey rsa:2048 -nodes \
  -keyout "$CERT_DIR/server.key" -out "$CERT_DIR/server.csr" \
  -config <(cat <<EOF
[req]
distinguished_name = dn
req_extensions = req_ext
prompt = no
[dn]
CN = redpanda-rag-sasl
[req_ext]
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
DNS.2 = redpanda-rag-local
IP.1 = 127.0.0.1
EOF
) 2>/dev/null
openssl x509 -req -in "$CERT_DIR/server.csr" \
  -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" -CAcreateserial \
  -out "$CERT_DIR/server.crt" -days 2 \
  -extfile <(cat <<EOF
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
DNS.2 = redpanda-rag-local
IP.1 = 127.0.0.1
EOF
) 2>/dev/null
# Redpanda runs as uid 101 in the container; make the key world-readable so the
# bind-mounted certs are readable by it (throwaway self-signed key).
chmod 644 "$CERT_DIR/ca.key" "$CERT_DIR/server.key"
echo "CA + server cert generated (SAN: DNS:localhost, DNS:redpanda-rag-local, IP:127.0.0.1)."

cat > "$CERT_DIR/redpanda.yaml" <<EOF
redpanda:
    data_directory: /var/lib/redpanda/data
    node_id: 0
    seed_servers: []
    rpc_server:
        address: 0.0.0.0
        port: 33145
    kafka_api:
        - name: SASL_TLS
          address: 0.0.0.0
          port: $KAFKA_PORT
          authentication_method: sasl
    kafka_api_tls:
        - name: SASL_TLS
          enabled: true
          cert_file: /etc/redpanda/certs/server.crt
          key_file: /etc/redpanda/certs/server.key
    admin:
        - address: 0.0.0.0
          port: $ADMIN_PORT
    advertised_rpc_api:
        address: 127.0.0.1
        port: 33145
    advertised_kafka_api:
        - name: SASL_TLS
          address: $KAFKA_HOST
          port: $KAFKA_PORT
    developer_mode: true
    auto_create_topics_enabled: true
    kafka_sasl_mechanisms:
        - $SASL_MECHANISM
    superusers:
        - $SASL_USER
rpk:
    overprovisioned: true
    coredump_dir: /var/lib/redpanda/coredump
    admin_api:
        addresses:
            - 127.0.0.1:$ADMIN_PORT
EOF

echo "=== 2. Starting throwaway ${CONTAINER} on ${KAFKA_HOST}:${KAFKA_PORT} ==="
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
# Start a sleeping container first so the redpanda.yaml can be copied onto the
# overlay filesystem (rpk rewrites the config in place and cannot do that to a
# bind-mounted file: the rename fails). The certs stay bind-mounted read-only.
docker run -d \
  --name "$CONTAINER" \
  --entrypoint /bin/sleep \
  -p "${KAFKA_HOST}:${KAFKA_PORT}:${KAFKA_PORT}" \
  -p "${KAFKA_HOST}:${ADMIN_PORT}:${ADMIN_PORT}" \
  -v "$CERT_DIR:/etc/redpanda/certs" \
  docker.redpanda.com/redpandadata/redpanda:latest \
  infinity >/dev/null
docker cp "$CERT_DIR/redpanda.yaml" "$CONTAINER:/etc/redpanda/redpanda.yaml"
docker exec -u root "$CONTAINER" chown redpanda:redpanda /etc/redpanda/redpanda.yaml
docker exec -d "$CONTAINER" rpk redpanda start \
  --config /etc/redpanda/redpanda.yaml \
  --overprovisioned --smp 1 --memory 1G --reserve-memory 0M --node-id 0 --check=false

echo "Waiting for Kafka listener on ${KAFKA_HOST}:${KAFKA_PORT}..."
elapsed=0
while ! "$PYTHON_BIN" - "$KAFKA_HOST" "$KAFKA_PORT" <<'PY' >/dev/null 2>&1
import socket
import sys
with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=0.5):
    pass
PY
do
  if [[ "$elapsed" -ge 90 ]]; then
    echo "Redpanda did not open ${KAFKA_HOST}:${KAFKA_PORT} within 90s." >&2
    exit 1
  fi
  sleep 1
  elapsed=$((elapsed + 1))
done
# Give redpanda a moment to finish listener startup before the Admin API call.
sleep 3

echo "=== 3. Bootstrapping SCRAM superuser '${SASL_USER}' via the Admin API ==="
docker exec "$CONTAINER" rpk acl user create "$SASL_USER" -p "$SASL_PASSWORD" --mechanism "$SASL_MECHANISM" >/dev/null

echo "=== 4a. RAG proof: pytest tests/integration/test_sasl_live.py over SASL_SSL ==="
(
  cd "$ROOT_DIR"
  RAG_SASL_LIVE=1 \
  RAG_SASL_PASSWORD="$SASL_PASSWORD" \
  RAG_SASL_CAFILE="$CERT_DIR/ca.crt" \
    "$PYTHON_BIN" -m pytest -q tests/integration/test_sasl_live.py
)

echo "=== 4b. SA proof: MemoryBrokerClient + RedpandaIdentityEventPublisher over SASL_SSL ==="
(
  cd "$ROOT_DIR"
  SA_ROOT="$SA_ROOT" \
  SASL_PASSWORD="$SASL_PASSWORD" \
  SASL_CAFILE="$CERT_DIR/ca.crt" \
    "$PYTHON_BIN" - <<'PY'
"""Host-side SA proof over SASL_SSL against the throwaway broker.

Imports simple_agent's MemoryBrokerClient and RedpandaIdentityEventPublisher
from their own checkout (sys.path trick used by the cross-repo interop test)
and proves each client connects to the SASL_SSL broker.
"""

import asyncio
import json
import os
import ssl
import sys
from pathlib import Path

# The heredoc runs with cwd=ROOT_DIR (the RAG checkout); SA is passed explicitly.
SA_ROOT = Path(os.environ["SA_ROOT"]).resolve()
for source in (
    SA_ROOT / "services/conversation-server/src",
    SA_ROOT / "services/identity-server/src",
    SA_ROOT / "libs/service-auth/src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from conversation_server.application.conversation_service import Actor
from conversation_server.infrastructure.memory_client import (
    MemoryBrokerClient,
    MemoryClientSettings,
)
from identity_server.infrastructure.redpanda_identity_publisher import (
    RedpandaIdentityEventPublisher,
    RedpandaPublisherSettings,
)
from identity_server.infrastructure.sqlite_identity_repository import (
    IdentityProvisioningOutboxRecord,
)
from simple_agent_service_auth import ServiceAuthSettings

BROKER = "127.0.0.1:19093"
CAFILE = os.environ["SASL_CAFILE"]
PASSWORD = os.environ["SASL_PASSWORD"]
TRACEPARENT = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"


def sasl_kwargs():
    return {
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "SCRAM-SHA-256",
        "sasl_plain_username": "admin",
        "sasl_plain_password": PASSWORD,
        "ssl_context": ssl.create_default_context(cafile=CAFILE),
    }


def _auth() -> ServiceAuthSettings:
    return ServiceAuthSettings(
        signing_key="local-dev-signing-key",
        issuer="simple-agent-local",
        audience="simple-agent-internal",
        ttl_seconds=300,
        allowed_services=("conversation-server",),
    )


async def read_until(topic: str, predicate, timeout: float = 30.0):
    reader = AIOKafkaConsumer(
        topic,
        bootstrap_servers=BROKER,
        group_id=f"sasl-proof-{os.getpid()}-{id(predicate)}",
        auto_offset_reset="earliest",
        **sasl_kwargs(),
    )
    await reader.start()
    try:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"no matching message on {topic}")
            message = await asyncio.wait_for(reader.getone(), timeout=remaining)
            try:
                value = json.loads(message.value)
            except Exception:
                value = message.value
            if predicate(value):
                return value
    finally:
        await reader.stop()


async def main() -> None:
    os.environ["REDPANDA_BOOTSTRAP_SERVERS"] = BROKER

    # --- MemoryBrokerClient: session.start published + read back ---
    client = MemoryBrokerClient(
        MemoryClientSettings(
            client_mode="broker",
            security_protocol="SASL_SSL",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username="admin",
            sasl_plain_password=PASSWORD,
            ssl_cafile=CAFILE,
        ),
        service_auth=_auth(),
    )
    await client.start()
    actor = Actor("usr_sasl", "tier_1")
    await client.record_session_start(
        actor=actor,
        conversation_id="con_sasl",
        agent_id="agent_sasl",
        request_id="req_sasl",
        traceparent=TRACEPARENT,
    )
    command = await read_until(
        "domain.memory.commands",
        lambda value: value.get("payload", {}).get("operation") == "session.start",
    )
    assert command["payload"]["operation"] == "session.start"
    print("SA MemoryBrokerClient: session.start published + read back over SASL_SSL")

    # --- MemoryBrokerClient: correlated reply awaited (request/reply path) ---
    lookup_task = asyncio.create_task(
        client.lookup(
            actor=actor,
            query="gluten",
            agent_id="agent_sasl",
            sources=None,
            request_id="req_lookup",
            traceparent=TRACEPARENT,
        )
    )
    lookup_command = await read_until(
        "domain.memory.commands",
        lambda value: value.get("payload", {}).get("operation") == "memory.lookup",
    )
    correlation_id = lookup_command["correlation_id"]
    responder = AIOKafkaProducer(bootstrap_servers=BROKER, **sasl_kwargs())
    await responder.start()
    try:
        reply = {
            "correlation_id": correlation_id,
            "message_type": "domain.result",
            "payload": {
                "operation": "memory.lookup",
                "result": {
                    "ok": True,
                    "query": "gluten",
                    "sources": ["chat_history"],
                    "results": {"chat_history": []},
                    "consulted": {"chat_history": True},
                },
            },
        }
        await responder.send_and_wait(
            "domain.memory.results",
            value=json.dumps(reply, separators=(",", ":")).encode("utf-8"),
        )
    finally:
        await responder.stop()
    result = await asyncio.wait_for(lookup_task, timeout=30)
    assert result["query"] == "gluten"
    print("SA MemoryBrokerClient: correlated lookup reply awaited over SASL_SSL")
    await client.close()

    # --- RedpandaIdentityEventPublisher: identity event published + read back ---
    publisher = RedpandaIdentityEventPublisher(
        RedpandaPublisherSettings(
            enabled=True,
            security_protocol="SASL_SSL",
            sasl_mechanism="SCRAM-SHA-256",
            sasl_plain_username="admin",
            sasl_plain_password=PASSWORD,
            ssl_cafile=CAFILE,
        )
    )
    event = IdentityProvisioningOutboxRecord(
        outbox_id="out_sasl_1",
        event_id="evt_sasl_1",
        event_type="identity.user.registered",
        owner_user_id="usr_sasl",
        identity_revision=1,
        payload={
            "event_id": "evt_sasl_1",
            "event_type": "identity.user.registered",
            "event_version": 1,
            "user_id": "usr_sasl",
            "identity_revision": 1,
            "role": "tier_1",
            "account_status": "active",
            "occurred_at": "2026-08-03T00:00:00+00:00",
        },
        idempotency_key="evt_sasl_1",
        request_id="req_sasl_id",
        traceparent=TRACEPARENT,
        status="pending",
        attempts=0,
        last_error_code=None,
        available_at="2026-08-03T00:00:00+00:00",
        published_at=None,
        created_at="2026-08-03T00:00:00+00:00",
        updated_at="2026-08-03T00:00:00+00:00",
    )
    await publisher.publish(event)
    identity_payload = await read_until(
        "identity.user.events", lambda value: value.get("event_id") == "evt_sasl_1"
    )
    assert identity_payload["event_id"] == "evt_sasl_1"
    print("SA RedpandaIdentityEventPublisher: identity event published + read back over SASL_SSL")

    print("SA SASL_SSL proof OK")


asyncio.run(main())
PY
)

echo "=== 5. Teardown ==="
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
echo "SASL_SSL verification passed (RAG + SA clients connect to the throwaway broker)."
