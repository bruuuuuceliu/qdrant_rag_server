#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${RAG_LOCAL_RUNTIME_DIR:-${ROOT_DIR}/.run}"
LOG_DIR="${RUNTIME_DIR}/logs"
STATE_FILE="${RUNTIME_DIR}/state.env"
MANAGER_PID_FILE="${RUNTIME_DIR}/manager.pid"
PROJECT_SERVICE_PID_FILE="${RUNTIME_DIR}/project-service.pid"
TASK_MANAGER_PID_FILE="${RUNTIME_DIR}/task-manager.pid"
TASK_SERVICE_PID_FILE="${RUNTIME_DIR}/task-service.pid"
WORKFLOW_LOG_PID_FILE="${RUNTIME_DIR}/workflow-log.pid"
INGESTION_WORKER_PID_FILE="${RUNTIME_DIR}/ingestion-worker.pid"
RETRIEVAL_INDEX_WORKER_PID_FILE="${RUNTIME_DIR}/retrieval-index-worker.pid"
RETRIEVAL_WORKER_PID_FILE="${RUNTIME_DIR}/retrieval-worker.pid"
STORAGE_NODE_PID_FILE="${RUNTIME_DIR}/storage-node.pid"
SQLITE_NODE_PID_FILE="${RUNTIME_DIR}/sqlite-node.pid"
REDIS_STATUS_PID_FILE="${RUNTIME_DIR}/redis-status.pid"
QDRANT_CID_FILE="${RUNTIME_DIR}/qdrant.cid"
QDRANT_LOG_PID_FILE="${RUNTIME_DIR}/qdrant-log.pid"
REDPANDA_CID_FILE="${RUNTIME_DIR}/redpanda.cid"
KAFKA_CID_FILE="${RUNTIME_DIR}/kafka.cid"
REDIS_CID_FILE="${RUNTIME_DIR}/redis.cid"
REDPANDA_CONSOLE_CID_FILE="${RUNTIME_DIR}/redpanda-console.cid"
REDIS_INSIGHT_CID_FILE="${RUNTIME_DIR}/redis-insight.cid"
ENV_FILE="${RAG_LOCAL_ENV_FILE:-${ROOT_DIR}/configs/local.env}"

INIT_PROJECT=0
RESET_FIRST=0
START_QDRANT=auto
FOREGROUND=0
START_SERVER=1
INFRA_ONLY=0
RUN_SMOKE=0
START_REDPANDA_CONSOLE=1
START_REDIS_INSIGHT=1
BROKER_TYPE_ARG=""
PROJECT_ID="${RAG_EXAMPLE_PROJECT_ID:-demo}"
PROJECT_TYPE="${RAG_EXAMPLE_PROJECT_TYPE:-website}"
QDRANT_CONTAINER="${RAG_QDRANT_CONTAINER:-qdrant-rag-local}"
QDRANT_VOLUME="${RAG_QDRANT_VOLUME:-qdrant-rag-local-data}"
REDPANDA_CONTAINER="${RAG_REDPANDA_CONTAINER:-redpanda-rag-local}"
KAFKA_CONTAINER="${RAG_KAFKA_CONTAINER:-kafka-rag-local}"
REDIS_CONTAINER="${RAG_REDIS_CONTAINER:-redis-rag-local}"
REDPANDA_CONSOLE_CONTAINER="${RAG_REDPANDA_CONSOLE_CONTAINER:-redpanda-console-rag-local}"
REDIS_INSIGHT_CONTAINER="${RAG_REDIS_INSIGHT_CONTAINER:-redis-insight-rag-local}"
REDIS_INSIGHT_VOLUME="${RAG_REDIS_INSIGHT_VOLUME:-redis-insight-rag-local-data}"
PYTHON_BIN="${PYTHON_BIN:-python}"

usage() {
  cat <<'EOF'
Usage:
  examples/local/run-all.sh [options]

Starts the local multi-service composition:
  - Qdrant container, when Docker is available and Qdrant is not already reachable
  - manager, task manager, domain services, helper nodes, storage, and SQLite nodes

Options:
  --init                         Initialize/seed local project config.
  --reset                        Stop existing local services before starting.
  --foreground                   Run manager in the foreground after setup.
  --no-server                    Run setup/init only; do not start services.
  --infra-only                   Start/verify local broker infrastructure and exit.
  --smoke                        Seed the project and verify health, ingest, and search.
  --broker VALUE                 Local Docker broker to use: redpanda or kafka. Default: redpanda.
  --ui                           Start local broker and Redis visualization UIs. Enabled by default.
  --no-ui                        Do not start local visualization UIs.
  --redpanda-console             Start Redpanda Console for broker topics/messages. Enabled by default.
  --no-redpanda-console          Do not start Redpanda Console.
  --redis-insight                Start Redis Insight for Redis task-status keys. Enabled by default.
  --no-redis-insight             Do not start Redis Insight.
  --env-file PATH                Source extra env vars before starting.
  --project-id VALUE             Project ID for --init. Default: demo.
  --project-type VALUE           Project type for --init. Default: website.
  --grpc-port VALUE              Manager gRPC port. Default: 50051.
  --embedding-provider VALUE     local, deterministic, openrouter, or remote. Default: local.
  --embedding-model VALUE        Embedding model name.
  --embedding-dimension VALUE    Embedding vector dimension. Default: 768.
  --qdrant                       Require/start local Docker Qdrant.
  --no-qdrant                    Do not try to start Qdrant.
  --qdrant-container VALUE       Docker container name. Default: qdrant-rag-local.
  --redpanda-container VALUE     Docker container name. Default: redpanda-rag-local.
  --kafka-container VALUE        Docker container name. Default: kafka-rag-local.
  --redis-container VALUE        Docker container name. Default: redis-rag-local.
  --redpanda-console-container VALUE
                                 Docker container name. Default: redpanda-console-rag-local.
  --redis-insight-container VALUE
                                 Docker container name. Default: redis-insight-rag-local.
  --generation                   Enable optional generation client wiring.
  --help                         Show this help.

Examples:
  examples/local/run-all.sh --init
  examples/local/run-all.sh --reset --init --grpc-port 50051
  examples/local/run-all.sh --init --embedding-provider openrouter
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --init)
      INIT_PROJECT=1
      shift
      ;;
    --reset)
      RESET_FIRST=1
      shift
      ;;
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --no-server)
      START_SERVER=0
      shift
      ;;
    --infra-only)
      INFRA_ONLY=1
      START_SERVER=1
      START_QDRANT=no
      shift
      ;;
    --smoke)
      RUN_SMOKE=1
      INIT_PROJECT=1
      shift
      ;;
    --broker)
      BROKER_TYPE_ARG="${2:?--broker requires a value}"
      shift 2
      ;;
    --ui)
      START_REDPANDA_CONSOLE=1
      START_REDIS_INSIGHT=1
      shift
      ;;
    --no-ui)
      START_REDPANDA_CONSOLE=0
      START_REDIS_INSIGHT=0
      shift
      ;;
    --redpanda-console)
      START_REDPANDA_CONSOLE=1
      shift
      ;;
    --no-redpanda-console)
      START_REDPANDA_CONSOLE=0
      shift
      ;;
    --redis-insight)
      START_REDIS_INSIGHT=1
      shift
      ;;
    --no-redis-insight)
      START_REDIS_INSIGHT=0
      shift
      ;;
    --env-file)
      ENV_FILE="${2:?--env-file requires a value}"
      shift 2
      ;;
    --project-id)
      PROJECT_ID="${2:?--project-id requires a value}"
      shift 2
      ;;
    --project-type)
      PROJECT_TYPE="${2:?--project-type requires a value}"
      shift 2
      ;;
    --grpc-port)
      export RAG_GRPC_PORT="${2:?--grpc-port requires a value}"
      shift 2
      ;;
    --embedding-provider)
      export RAG_EMBEDDING_PROVIDER="${2:?--embedding-provider requires a value}"
      shift 2
      ;;
    --embedding-model)
      export RAG_EMBEDDING_MODEL="${2:?--embedding-model requires a value}"
      shift 2
      ;;
    --embedding-dimension)
      export RAG_EMBEDDING_DIMENSION="${2:?--embedding-dimension requires a value}"
      shift 2
      ;;
    --qdrant)
      START_QDRANT=yes
      shift
      ;;
    --no-qdrant)
      START_QDRANT=no
      shift
      ;;
    --qdrant-container)
      QDRANT_CONTAINER="${2:?--qdrant-container requires a value}"
      shift 2
      ;;
    --redpanda-container)
      REDPANDA_CONTAINER="${2:?--redpanda-container requires a value}"
      shift 2
      ;;
    --kafka-container)
      KAFKA_CONTAINER="${2:?--kafka-container requires a value}"
      shift 2
      ;;
    --redis-container)
      REDIS_CONTAINER="${2:?--redis-container requires a value}"
      shift 2
      ;;
    --redpanda-console-container)
      REDPANDA_CONSOLE_CONTAINER="${2:?--redpanda-console-container requires a value}"
      shift 2
      ;;
    --redis-insight-container)
      REDIS_INSIGHT_CONTAINER="${2:?--redis-insight-container requires a value}"
      shift 2
      ;;
    --generation)
      export RAG_GENERATION_ENABLED=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$RUN_SMOKE" -eq 1 && "$FOREGROUND" -eq 1 ]]; then
  echo "--smoke cannot be combined with --foreground." >&2
  exit 2
fi
if [[ "$RUN_SMOKE" -eq 1 && "$INFRA_ONLY" -eq 1 ]]; then
  echo "--smoke cannot be combined with --infra-only." >&2
  exit 2
fi
if [[ "$RUN_SMOKE" -eq 1 && "$START_SERVER" -eq 0 ]]; then
  echo "--smoke cannot be combined with --no-server." >&2
  exit 2
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
if [[ -n "$BROKER_TYPE_ARG" ]]; then
  export BROKER_TYPE="$BROKER_TYPE_ARG"
fi

export RAG_LOCAL_DATA_DIR="${RAG_LOCAL_DATA_DIR:-${RUNTIME_DIR}/data}"
export RAG_CONFIG_PROFILE="${RAG_CONFIG_PROFILE:-local}"
export PROJECT_CONFIG_DB_PATH="${PROJECT_CONFIG_DB_PATH:-${RAG_LOCAL_DATA_DIR}/project_config.db}"
export RAG_RESPONSE_CACHE_DB_PATH="${RAG_RESPONSE_CACHE_DB_PATH:-${RAG_LOCAL_DATA_DIR}/response_cache.db}"
export INGESTION_JOB_DB_PATH="${INGESTION_JOB_DB_PATH:-${RAG_LOCAL_DATA_DIR}/ingestion_jobs.db}"
export WORKFLOW_LOG_DB_PATH="${WORKFLOW_LOG_DB_PATH:-${RAG_LOCAL_DATA_DIR}/workflow_log.db}"
export RAG_OBJECT_STORAGE_BASE_PATH="${RAG_OBJECT_STORAGE_BASE_PATH:-${RAG_LOCAL_DATA_DIR}/raw_storage}"
export RETRIEVAL_PLACEMENT_ENABLED="${RETRIEVAL_PLACEMENT_ENABLED:-true}"
export RETRIEVAL_PLACEMENT_DB_PATH="${RETRIEVAL_PLACEMENT_DB_PATH:-${RAG_LOCAL_DATA_DIR}/placement.db}"
export RETRIEVAL_PLACEMENT_ROUTING_MODE="${RETRIEVAL_PLACEMENT_ROUTING_MODE:-project_single}"
export RETRIEVAL_PLACEMENT_BUCKET_COUNT="${RETRIEVAL_PLACEMENT_BUCKET_COUNT:-1}"
export RETRIEVAL_PLACEMENT_REPLICATION_FACTOR="${RETRIEVAL_PLACEMENT_REPLICATION_FACTOR:-1}"
export RETRIEVAL_PLACEMENT_SHARD_ID="${RETRIEVAL_PLACEMENT_SHARD_ID:-local-qdrant}"
export RETRIEVAL_PLACEMENT_CLUSTER_ID="${RETRIEVAL_PLACEMENT_CLUSTER_ID:-local}"
export RAG_GRPC_PORT="${RAG_GRPC_PORT:-50051}"
export RAG_QDRANT_HOST="${RAG_QDRANT_HOST:-localhost}"
export RAG_QDRANT_PORT="${RAG_QDRANT_PORT:-6333}"
export RAG_QDRANT_GRPC_PORT="${RAG_QDRANT_GRPC_PORT:-6334}"
export PROJECT_MAX_PER_PROJECT="${PROJECT_MAX_PER_PROJECT:-20}"
export PROJECT_MAX_PER_USER="${PROJECT_MAX_PER_USER:-5}"
export INGESTION_WORKER_COUNT="${INGESTION_WORKER_COUNT:-1}"
export INGESTION_QUEUE_MAXSIZE="${INGESTION_QUEUE_MAXSIZE:-100}"
export INGESTION_HELPER_COMMAND_TOPIC="${INGESTION_HELPER_COMMAND_TOPIC:-helper.ingestion.commands}"
export WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC="${WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC:-domain.workflow_log.commands}"
export WORKFLOW_LOG_AUDIT_TOPIC="${WORKFLOW_LOG_AUDIT_TOPIC:-audit.events}"
export RETRIEVAL_HELPER_COMMAND_TOPIC="${RETRIEVAL_HELPER_COMMAND_TOPIC:-helper.retrieval.commands}"
export RETRIEVAL_INDEX_WORKER_ENABLED="${RETRIEVAL_INDEX_WORKER_ENABLED:-true}"
export RETRIEVAL_INDEX_HELPER_COMMAND_TOPIC="${RETRIEVAL_INDEX_HELPER_COMMAND_TOPIC:-helper.retrieval_index.commands}"
export RAG_EMBEDDING_PROVIDER="${RAG_EMBEDDING_PROVIDER:-local}"
export RAG_EMBEDDING_MODEL="${RAG_EMBEDDING_MODEL:-BAAI/bge-base-en-v1.5}"
export RAG_EMBEDDING_DEVICE="${RAG_EMBEDDING_DEVICE:-cpu}"
export RAG_EMBEDDING_DIMENSION="${RAG_EMBEDDING_DIMENSION:-768}"
if [[ "$RUN_SMOKE" -eq 1 && -z "${RAG_EXAMPLE_EMBEDDING_VERSION:-}" ]]; then
  export RAG_EXAMPLE_EMBEDDING_VERSION="smoke_${RAG_EMBEDDING_PROVIDER}_${RAG_EMBEDDING_DIMENSION}"
fi
export RAG_EMBEDDING_BASE_URL="${RAG_EMBEDDING_BASE_URL:-https://openrouter.ai/api/v1/embeddings}"
export RAG_GENERATION_ENABLED="${RAG_GENERATION_ENABLED:-false}"
BROKER_TYPE="$(printf '%s' "${BROKER_TYPE:-redpanda}" | tr '[:upper:]' '[:lower:]')"
export BROKER_TYPE
export BROKER_BOOTSTRAP_SERVERS="${BROKER_BOOTSTRAP_SERVERS:-127.0.0.1:9092}"
export BROKER_CLIENT_ID="${BROKER_CLIENT_ID:-qdrant-rag-local}"
export BROKER_REQUEST_TIMEOUT_SECONDS="${BROKER_REQUEST_TIMEOUT_SECONDS:-30}"
export BROKER_TOPIC_PREFIX="${BROKER_TOPIC_PREFIX:-qdrant-rag-local.}"
export BROKER_TOPIC_PARTITIONS="${BROKER_TOPIC_PARTITIONS:-1}"
export BROKER_LAG_TARGETS="${BROKER_LAG_TARGETS:-}"
export REDPANDA_CONSOLE_PORT="${REDPANDA_CONSOLE_PORT:-8088}"
export REDIS_INSIGHT_PORT="${REDIS_INSIGHT_PORT:-5540}"
export INFRA_ONLY
export MANAGER_TASK_INTAKE_TOPIC="${MANAGER_TASK_INTAKE_TOPIC:-task.intake}"
export TASK_MANAGER_SERVICE_NAME="${TASK_MANAGER_SERVICE_NAME:-task_manager_service}"
export TASK_MANAGER_TASK_INTAKE_TOPIC="${TASK_MANAGER_TASK_INTAKE_TOPIC:-${MANAGER_TASK_INTAKE_TOPIC}}"
export TASK_MANAGER_TASK_REQUEST_TOPIC="${TASK_MANAGER_TASK_REQUEST_TOPIC:-task.requests}"
export TASK_MANAGER_TASK_EVENT_TOPIC="${TASK_MANAGER_TASK_EVENT_TOPIC:-task.events}"
export TASK_MANAGER_TASK_RESULT_TOPIC="${TASK_MANAGER_TASK_RESULT_TOPIC:-task.results}"
export TASK_SERVICE_NAME="${TASK_SERVICE_NAME:-task_service}"
export TASK_SERVICE_TASK_REQUEST_TOPIC="${TASK_SERVICE_TASK_REQUEST_TOPIC:-${TASK_MANAGER_TASK_REQUEST_TOPIC}}"
export TASK_SERVICE_PROJECT_PLAN_REQUEST_TOPIC="${TASK_SERVICE_PROJECT_PLAN_REQUEST_TOPIC:-project.plan.requests}"
export TASK_SERVICE_PROJECT_PLAN_RESULT_TOPIC="${TASK_SERVICE_PROJECT_PLAN_RESULT_TOPIC:-project.plan.results}"
export TASK_SERVICE_TASK_EVENT_TOPIC="${TASK_SERVICE_TASK_EVENT_TOPIC:-${TASK_MANAGER_TASK_EVENT_TOPIC}}"
export TASK_SERVICE_TASK_RESULT_TOPIC="${TASK_SERVICE_TASK_RESULT_TOPIC:-${TASK_MANAGER_TASK_RESULT_TOPIC}}"
export TASK_SERVICE_DEAD_LETTER_TOPIC="${TASK_SERVICE_DEAD_LETTER_TOPIC:-task.dead_letters}"
export TASK_SERVICE_MAX_ATTEMPTS="${TASK_SERVICE_MAX_ATTEMPTS:-3}"
export TASK_SERVICE_HELPER_LEASE_SECONDS="${TASK_SERVICE_HELPER_LEASE_SECONDS:-300}"
export TASK_SERVICE_RETRY_BACKOFF_SECONDS="${TASK_SERVICE_RETRY_BACKOFF_SECONDS:-0}"
export TASK_SERVICE_RECOVERY_ENABLED="${TASK_SERVICE_RECOVERY_ENABLED:-true}"
export TASK_SERVICE_RECOVERY_POLL_SECONDS="${TASK_SERVICE_RECOVERY_POLL_SECONDS:-2.0}"
export TASK_SERVICE_RECOVERY_BATCH_SIZE="${TASK_SERVICE_RECOVERY_BATCH_SIZE:-25}"
export PROJECT_PLAN_REQUEST_TOPIC="${PROJECT_PLAN_REQUEST_TOPIC:-${TASK_SERVICE_PROJECT_PLAN_REQUEST_TOPIC}}"
export PROJECT_PLAN_RESULT_TOPIC="${PROJECT_PLAN_RESULT_TOPIC:-${TASK_SERVICE_PROJECT_PLAN_RESULT_TOPIC}}"
export REDIS_TASK_STATUS_URL="${REDIS_TASK_STATUS_URL:-redis://127.0.0.1:6379/0}"
export REDIS_TASK_STATUS_KEY_PREFIX="${REDIS_TASK_STATUS_KEY_PREFIX:-qdrant-rag-local:task:}"
export REDIS_TASK_COMPLETED_TTL_SECONDS="${REDIS_TASK_COMPLETED_TTL_SECONDS:-86400}"
export STORAGE_NODE_ROOT="${STORAGE_NODE_ROOT:-${RAG_LOCAL_DATA_DIR}/storage_node}"
export SQLITE_NODE_DATABASE_ROOT="${SQLITE_NODE_DATABASE_ROOT:-${RAG_LOCAL_DATA_DIR}/sqlite}"
export TASK_SERVICE_STATE_DB_PATH="${TASK_SERVICE_STATE_DB_PATH:-${RAG_LOCAL_DATA_DIR}/task_service_state.db}"

allocate_sqlite_databases() {
  "$PYTHON_BIN" - <<'PY'
import asyncio
import os

from sqlite_node import SQLiteNodeSettings, SQLiteNodeService


DATABASES = (
    ("project_service", "project_config", "project domain configuration", "PROJECT_CONFIG_DB_PATH"),
    ("retrieval_service", "response_cache", "retrieval response cache", "RAG_RESPONSE_CACHE_DB_PATH"),
    ("ingestion_service", "ingestion_jobs", "ingestion job metadata", "INGESTION_JOB_DB_PATH"),
    ("workflow_log_service", "workflow_log", "workflow audit log", "WORKFLOW_LOG_DB_PATH"),
    ("retrieval_service", "retrieval_placement", "retrieval shard placement", "RETRIEVAL_PLACEMENT_DB_PATH"),
    ("task_service", "task_service_state", "task-service durable fan-in state", "TASK_SERVICE_STATE_DB_PATH"),
)


async def main() -> None:
    settings = SQLiteNodeSettings.from_values(dict(os.environ))
    service = SQLiteNodeService(database_root=settings.database_root)
    await service.initialize()
    for owner, database_name, purpose, env_name in DATABASES:
        path = await service.allocate_database(
            owner_service=owner,
            database_name=database_name,
            purpose=purpose,
        )
        await service.record_schema_version(
            owner_service=owner,
            database_name=database_name,
            schema_name=database_name,
            version=1,
        )
        await service.record_health_check(
            owner_service=owner,
            database_name=database_name,
            ok=path.parent.exists(),
        )
        print(f"export {env_name}={path}")


asyncio.run(main())
PY
}

while IFS= read -r assignment; do
  export "${assignment#export }"
done < <(allocate_sqlite_databases)

normalize_proxy_env() {
  local name value fixed
  for name in \
    ALL_PROXY all_proxy \
    HTTP_PROXY http_proxy \
    HTTPS_PROXY https_proxy \
    WSS_PROXY wss_proxy \
    WS_PROXY ws_proxy; do
    value="${!name:-}"
    case "$value" in
      socks://*)
        fixed="socks5://${value#socks://}"
        export "$name=$fixed"
        echo "Normalized ${name} proxy scheme from socks:// to socks5:// for httpx compatibility."
        ;;
    esac
  done
}

normalize_proxy_env

validate_mode_combination() {
  case "$BROKER_TYPE" in
    redpanda|kafka)
      ;;
    *)
      echo "BROKER_TYPE must be one of: redpanda, kafka." >&2
      exit 2
      ;;
  esac
}

validate_mode_combination

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
  else
    echo "Python runtime not found. Set PYTHON_BIN or install python/python3." >&2
    exit 1
  fi
fi
export PYTHON_BIN

mkdir -p "$RUNTIME_DIR" "$LOG_DIR" "$RAG_LOCAL_DATA_DIR" "$RAG_OBJECT_STORAGE_BASE_PATH"

if [[ "$RESET_FIRST" -eq 1 ]]; then
  "${SCRIPT_DIR}/stop-all.sh" --clean || true
  mkdir -p "$RUNTIME_DIR" "$LOG_DIR" "$RAG_LOCAL_DATA_DIR" "$RAG_OBJECT_STORAGE_BASE_PATH"
fi

cd "$ROOT_DIR"

is_qdrant_reachable() {
  command -v curl >/dev/null 2>&1 && \
    curl -fsS "http://${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}/collections" >/dev/null 2>&1
}

start_qdrant_if_needed() {
  local qdrant_log="${LOG_DIR}/qdrant.log"
  mkdir -p "$(dirname "$qdrant_log")"
  : > "$qdrant_log"
  if [[ "$START_QDRANT" == "no" ]]; then
    echo "Qdrant startup disabled by --no-qdrant." >> "$qdrant_log"
    return 0
  fi
  if is_qdrant_reachable; then
    echo "Qdrant already reachable at ${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}."
    echo "Qdrant already reachable at ${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}; no local container log attached." >> "$qdrant_log"
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    if [[ "$START_QDRANT" == "yes" ]]; then
      echo "Docker is required for --qdrant but was not found." >&2
      exit 1
    fi
    echo "Warning: Qdrant is not reachable and Docker was not found." >&2
    echo "Start Qdrant yourself or rerun with Docker available." >&2
    return 0
  fi

  if ! docker info >/dev/null 2>&1; then
    if [[ "$START_QDRANT" == "yes" ]]; then
      echo "Docker is installed but the daemon is not accessible." >&2
      echo "Check Docker is running and that this user can access /var/run/docker.sock." >&2
      exit 1
    fi
    echo "Warning: Qdrant is not reachable and Docker is not accessible." >&2
    echo "Start Qdrant yourself or rerun after Docker access is fixed." >&2
    echo "Docker daemon was not accessible; Qdrant was not started." >> "$qdrant_log"
    return 0
  fi

  if docker ps -a --format '{{.Names}}' | grep -Fxq "$QDRANT_CONTAINER"; then
    docker start "$QDRANT_CONTAINER" >/dev/null
  else
    docker run -d \
      --name "$QDRANT_CONTAINER" \
      -p "${RAG_QDRANT_PORT}:6333" \
      -p "${RAG_QDRANT_GRPC_PORT}:6334" \
      -v "${QDRANT_VOLUME}:/qdrant/storage" \
      qdrant/qdrant >/dev/null
  fi
  docker inspect --format '{{.Id}}' "$QDRANT_CONTAINER" > "$QDRANT_CID_FILE" 2>/dev/null || true
  start_qdrant_log_collector "$qdrant_log"

  for _ in $(seq 1 30); do
    if is_qdrant_reachable; then
      echo "Qdrant started at ${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}."
      return 0
    fi
    sleep 1
  done
  echo "Warning: Qdrant container started but health check did not pass." >&2
}

start_redpanda_if_needed() {
  if is_tcp_port_open "127.0.0.1" "9092"; then
    echo "Kafka-compatible broker already reachable at 127.0.0.1:9092; using topic prefix '${BROKER_TOPIC_PREFIX}'."
    return 0
  fi
  require_docker "Redpanda"
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$REDPANDA_CONTAINER"; then
    docker start "$REDPANDA_CONTAINER" >/dev/null
  else
    docker run -d \
      --name "$REDPANDA_CONTAINER" \
      -p 9092:9092 \
      -p 9644:9644 \
      docker.redpanda.com/redpandadata/redpanda:latest \
      redpanda start \
      --overprovisioned \
      --smp 1 \
      --memory 1G \
      --reserve-memory 0M \
      --node-id 0 \
      --check=false \
      --kafka-addr 0.0.0.0:9092 \
      --advertise-kafka-addr 127.0.0.1:9092 >/dev/null
  fi
  docker inspect --format '{{.Id}}' "$REDPANDA_CONTAINER" > "$REDPANDA_CID_FILE" 2>/dev/null || true
  wait_for_tcp "Redpanda" "127.0.0.1" "9092" 90
}

start_kafka_if_needed() {
  if is_tcp_port_open "127.0.0.1" "9092"; then
    echo "Kafka-compatible broker already reachable at 127.0.0.1:9092; using topic prefix '${BROKER_TOPIC_PREFIX}'."
    return 0
  fi
  require_docker "Kafka"
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$KAFKA_CONTAINER"; then
    docker start "$KAFKA_CONTAINER" >/dev/null
  else
    docker run -d \
      --name "$KAFKA_CONTAINER" \
      -p 9092:9092 \
      -e KAFKA_NODE_ID=1 \
      -e KAFKA_PROCESS_ROLES=broker,controller \
      -e KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093 \
      -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://127.0.0.1:9092 \
      -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
      -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT \
      -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@127.0.0.1:9093 \
      -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
      -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
      -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
      -e KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0 \
      apache/kafka:latest >/dev/null
  fi
  docker inspect --format '{{.Id}}' "$KAFKA_CONTAINER" > "$KAFKA_CID_FILE" 2>/dev/null || true
  wait_for_tcp "Kafka" "127.0.0.1" "9092" 120
}

start_broker_if_needed() {
  case "$BROKER_TYPE" in
    redpanda)
      start_redpanda_if_needed
      ;;
    kafka)
      start_kafka_if_needed
      ;;
  esac
}

start_redis_if_needed() {
  if is_tcp_port_open "127.0.0.1" "6379"; then
    echo "Redis already reachable at 127.0.0.1:6379."
    return 0
  fi
  require_docker "Redis"
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$REDIS_CONTAINER"; then
    docker start "$REDIS_CONTAINER" >/dev/null
  else
    docker run -d --name "$REDIS_CONTAINER" -p 6379:6379 redis:7-alpine >/dev/null
  fi
  docker inspect --format '{{.Id}}' "$REDIS_CONTAINER" > "$REDIS_CID_FILE" 2>/dev/null || true
  wait_for_tcp "Redis" "127.0.0.1" "6379" 60
}

start_redpanda_console_if_needed() {
  if [[ "$START_REDPANDA_CONSOLE" -ne 1 ]]; then
    return 0
  fi
  if is_tcp_port_open "127.0.0.1" "$REDPANDA_CONSOLE_PORT"; then
    echo "Redpanda Console already reachable at http://127.0.0.1:${REDPANDA_CONSOLE_PORT}."
    return 0
  fi
  require_docker "Redpanda Console"
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$REDPANDA_CONSOLE_CONTAINER"; then
    docker start "$REDPANDA_CONSOLE_CONTAINER" >/dev/null
  else
    docker run -d \
      --name "$REDPANDA_CONSOLE_CONTAINER" \
      --network host \
      -e "KAFKA_BROKERS=${BROKER_BOOTSTRAP_SERVERS}" \
      -e "SERVER_LISTENPORT=${REDPANDA_CONSOLE_PORT}" \
      -e "SERVER_LISTENADDRESS=0.0.0.0" \
      docker.redpanda.com/redpandadata/console:latest >/dev/null
  fi
  docker inspect --format '{{.Id}}' "$REDPANDA_CONSOLE_CONTAINER" > "$REDPANDA_CONSOLE_CID_FILE" 2>/dev/null || true
  wait_for_tcp "Redpanda Console" "127.0.0.1" "$REDPANDA_CONSOLE_PORT" 90
}

start_redis_insight_if_needed() {
  if [[ "$START_REDIS_INSIGHT" -ne 1 ]]; then
    return 0
  fi
  if is_tcp_port_open "127.0.0.1" "$REDIS_INSIGHT_PORT"; then
    echo "Redis Insight already reachable at http://127.0.0.1:${REDIS_INSIGHT_PORT}."
    return 0
  fi
  require_docker "Redis Insight"
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$REDIS_INSIGHT_CONTAINER"; then
    docker start "$REDIS_INSIGHT_CONTAINER" >/dev/null
  else
    docker run -d \
      --name "$REDIS_INSIGHT_CONTAINER" \
      --network host \
      -v "${REDIS_INSIGHT_VOLUME}:/data" \
      -e "RI_APP_HOST=0.0.0.0" \
      -e "RI_APP_PORT=${REDIS_INSIGHT_PORT}" \
      redis/redisinsight:latest >/dev/null
  fi
  docker inspect --format '{{.Id}}' "$REDIS_INSIGHT_CONTAINER" > "$REDIS_INSIGHT_CID_FILE" 2>/dev/null || true
  wait_for_tcp "Redis Insight" "127.0.0.1" "$REDIS_INSIGHT_PORT" 90
}

require_docker() {
  local label="$1"
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required to start local ${label}." >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but the daemon is not accessible for local ${label}." >&2
    exit 1
  fi
}

wait_for_tcp() {
  local label="$1"
  local host="$2"
  local port="$3"
  local timeout_seconds="${4:-60}"
  local elapsed=0
  while [[ "$elapsed" -lt "$timeout_seconds" ]]; do
    if is_tcp_port_open "$host" "$port"; then
      echo "${label} reachable at ${host}:${port}."
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "${label} did not open ${host}:${port} within ${timeout_seconds}s." >&2
  exit 1
}

start_qdrant_log_collector() {
  local qdrant_log="$1"
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  if [[ -f "$QDRANT_LOG_PID_FILE" ]]; then
    local old_pid
    old_pid="$(cat "$QDRANT_LOG_PID_FILE" 2>/dev/null || true)"
    if is_pid_alive "$old_pid"; then
      return 0
    fi
    rm -f "$QDRANT_LOG_PID_FILE"
  fi
  docker logs -f "$QDRANT_CONTAINER" >> "$qdrant_log" 2>&1 &
  echo "$!" > "$QDRANT_LOG_PID_FILE"
}

check_runtime_dependencies() {
  "$PYTHON_BIN" - <<'PY'
import importlib.util
import sys

required = {
    "grpc": "grpcio",
    "aiokafka": "aiokafka",
    "redis": "redis",
}
if __import__("os").environ.get("INFRA_ONLY") != "1":
    required["qdrant_client"] = "qdrant-client"
if (
    __import__("os").environ.get("INFRA_ONLY") != "1"
    and __import__("os").environ.get("RAG_EMBEDDING_PROVIDER", "local").lower() == "local"
):
    required["sentence_transformers"] = "sentence-transformers"
missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
if missing:
    print("Missing required runtime dependencies: " + ", ".join(missing), file=sys.stderr)
    print('Install them with: python -m pip install -e ".[dev]"', file=sys.stderr)
    raise SystemExit(1)
PY
}

validate_provider_config() {
  case "${RAG_EMBEDDING_PROVIDER}" in
    local|deterministic|hash|smoke)
      ;;
    openrouter|remote|openai_compatible)
      if [[ -z "${RAG_EMBEDDING_API_KEY:-}" ]]; then
        echo "RAG_EMBEDDING_API_KEY is required for RAG_EMBEDDING_PROVIDER=${RAG_EMBEDDING_PROVIDER}." >&2
        exit 1
      fi
      ;;
    *)
      echo "RAG_EMBEDDING_PROVIDER must be one of: local, deterministic, hash, smoke, openrouter, remote, openai_compatible" >&2
      exit 1
      ;;
  esac
}

validate_runtime_config() {
  return 0
}

init_project_config() {
  PROJECT_ID="$PROJECT_ID" PROJECT_TYPE="$PROJECT_TYPE" "$PYTHON_BIN" - <<'PY'
import asyncio
import os
from pathlib import Path

from project_service.config import SQLiteProjectConfigRepository
from project_service.schemas import ProjectConfig


async def main() -> None:
    project_id = os.environ["PROJECT_ID"]
    project_type = os.environ["PROJECT_TYPE"]
    active_embedding_version = _safe_identifier(
        os.environ.get("RAG_EXAMPLE_EMBEDDING_VERSION", "v1")
    )
    repo = SQLiteProjectConfigRepository(Path(os.environ["PROJECT_CONFIG_DB_PATH"]))
    await repo.initialize()
    await repo.upsert_project(
        ProjectConfig(
            project_id=project_id,
            project_type=project_type,
            active_embedding_version=active_embedding_version,
            embedding_model=os.environ["RAG_EMBEDDING_MODEL"],
            reranker_model="none",
            chunker_config={
                "domains": ["example.com"],
                "default_locale": "en",
            },
            retrieval_config={"candidate_count": 20, "top_k": 5},
        )
    )
    print(f"Initialized project {project_id!r} as type {project_type!r}")


def _safe_identifier(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char == "_" else "_"
        for char in value.strip()
    ).strip("_")
    return cleaned or "v1"


asyncio.run(main())
PY
}

is_pid_alive() {
  [[ -n "${1:-}" ]] && kill -0 "$1" >/dev/null 2>&1
}

is_tcp_port_open() {
  local host="$1"
  local port="$2"
  "$PYTHON_BIN" - "$host" "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
with socket.create_connection((host, port), timeout=0.5):
    pass
PY
}

wait_for_service_port() {
  local label="$1"
  local pid="$2"
  local host="$3"
  local port="$4"
  local log_file="$5"
  local timeout_seconds="${6:-90}"
  local elapsed=0
  while [[ "$elapsed" -lt "$timeout_seconds" ]]; do
    if ! is_pid_alive "$pid"; then
      echo "${label} failed to stay running. Log follows:" >&2
      sed -n '1,200p' "$log_file" >&2 || true
      return 1
    fi
    if is_tcp_port_open "$host" "$port"; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "${label} did not open ${host}:${port} within ${timeout_seconds}s. Log follows:" >&2
  sed -n '1,200p' "$log_file" >&2 || true
  return 1
}

ensure_not_already_running() {
  if [[ -f "$MANAGER_PID_FILE" ]]; then
    local old_pid
    old_pid="$(cat "$MANAGER_PID_FILE" 2>/dev/null || true)"
    if is_pid_alive "$old_pid"; then
      echo "Manager is already running with PID ${old_pid}. Use examples/local/stop-all.sh first." >&2
      exit 1
    fi
    rm -f "$MANAGER_PID_FILE"
  fi
  if [[ -f "$INGESTION_WORKER_PID_FILE" ]]; then
    local old_worker_pid
    old_worker_pid="$(cat "$INGESTION_WORKER_PID_FILE" 2>/dev/null || true)"
    if is_pid_alive "$old_worker_pid"; then
      echo "Ingestion worker is already running with PID ${old_worker_pid}. Use examples/local/stop-all.sh first." >&2
      exit 1
    fi
    rm -f "$INGESTION_WORKER_PID_FILE"
  fi
  if [[ -f "$RETRIEVAL_INDEX_WORKER_PID_FILE" ]]; then
    local old_index_pid
    old_index_pid="$(cat "$RETRIEVAL_INDEX_WORKER_PID_FILE" 2>/dev/null || true)"
    if is_pid_alive "$old_index_pid"; then
      echo "Retrieval index worker is already running with PID ${old_index_pid}. Use examples/local/stop-all.sh first." >&2
      exit 1
    fi
    rm -f "$RETRIEVAL_INDEX_WORKER_PID_FILE"
  fi
  if [[ -f "$PROJECT_SERVICE_PID_FILE" ]]; then
    local old_project_pid
    old_project_pid="$(cat "$PROJECT_SERVICE_PID_FILE" 2>/dev/null || true)"
    if is_pid_alive "$old_project_pid"; then
      echo "Project service is already running with PID ${old_project_pid}. Use examples/local/stop-all.sh first." >&2
      exit 1
    fi
    rm -f "$PROJECT_SERVICE_PID_FILE"
  fi
  for pid_file in \
    "$TASK_MANAGER_PID_FILE" \
    "$TASK_SERVICE_PID_FILE" \
    "$WORKFLOW_LOG_PID_FILE" \
    "$RETRIEVAL_WORKER_PID_FILE" \
    "$STORAGE_NODE_PID_FILE" \
    "$SQLITE_NODE_PID_FILE" \
    "$REDIS_STATUS_PID_FILE"; do
    if [[ -f "$pid_file" ]]; then
      local old_pid
      old_pid="$(cat "$pid_file" 2>/dev/null || true)"
      if is_pid_alive "$old_pid"; then
        echo "Service is already running with PID ${old_pid}. Use examples/local/stop-all.sh first." >&2
        exit 1
      fi
      rm -f "$pid_file"
    fi
  done
}

write_state() {
  cat > "$STATE_FILE" <<EOF
ROOT_DIR=${ROOT_DIR}
RUNTIME_DIR=${RUNTIME_DIR}
RAG_LOCAL_DATA_DIR=${RAG_LOCAL_DATA_DIR}
PROJECT_CONFIG_DB_PATH=${PROJECT_CONFIG_DB_PATH}
INGESTION_JOB_DB_PATH=${INGESTION_JOB_DB_PATH}
RAG_GRPC_PORT=${RAG_GRPC_PORT}
RAG_QDRANT_HOST=${RAG_QDRANT_HOST}
RAG_QDRANT_PORT=${RAG_QDRANT_PORT}
RAG_QDRANT_GRPC_PORT=${RAG_QDRANT_GRPC_PORT}
QDRANT_CONTAINER=${QDRANT_CONTAINER}
QDRANT_VOLUME=${QDRANT_VOLUME}
REDPANDA_CONTAINER=${REDPANDA_CONTAINER}
KAFKA_CONTAINER=${KAFKA_CONTAINER}
REDIS_CONTAINER=${REDIS_CONTAINER}
REDPANDA_CONSOLE_CONTAINER=${REDPANDA_CONSOLE_CONTAINER}
REDIS_INSIGHT_CONTAINER=${REDIS_INSIGHT_CONTAINER}
REDIS_INSIGHT_VOLUME=${REDIS_INSIGHT_VOLUME}
BROKER_TYPE=${BROKER_TYPE}
BROKER_BOOTSTRAP_SERVERS=${BROKER_BOOTSTRAP_SERVERS}
BROKER_CLIENT_ID=${BROKER_CLIENT_ID}
BROKER_TOPIC_PREFIX=${BROKER_TOPIC_PREFIX}
BROKER_LAG_TARGETS=${BROKER_LAG_TARGETS}
REDPANDA_CONSOLE_PORT=${REDPANDA_CONSOLE_PORT}
REDIS_INSIGHT_PORT=${REDIS_INSIGHT_PORT}
MANAGER_TASK_INTAKE_TOPIC=${MANAGER_TASK_INTAKE_TOPIC}
TASK_MANAGER_SERVICE_NAME=${TASK_MANAGER_SERVICE_NAME}
TASK_MANAGER_TASK_INTAKE_TOPIC=${TASK_MANAGER_TASK_INTAKE_TOPIC}
TASK_MANAGER_TASK_REQUEST_TOPIC=${TASK_MANAGER_TASK_REQUEST_TOPIC}
TASK_MANAGER_TASK_EVENT_TOPIC=${TASK_MANAGER_TASK_EVENT_TOPIC}
TASK_MANAGER_TASK_RESULT_TOPIC=${TASK_MANAGER_TASK_RESULT_TOPIC}
TASK_SERVICE_NAME=${TASK_SERVICE_NAME}
TASK_SERVICE_TASK_REQUEST_TOPIC=${TASK_SERVICE_TASK_REQUEST_TOPIC}
TASK_SERVICE_PROJECT_PLAN_REQUEST_TOPIC=${TASK_SERVICE_PROJECT_PLAN_REQUEST_TOPIC}
TASK_SERVICE_PROJECT_PLAN_RESULT_TOPIC=${TASK_SERVICE_PROJECT_PLAN_RESULT_TOPIC}
TASK_SERVICE_TASK_EVENT_TOPIC=${TASK_SERVICE_TASK_EVENT_TOPIC}
TASK_SERVICE_TASK_RESULT_TOPIC=${TASK_SERVICE_TASK_RESULT_TOPIC}
TASK_SERVICE_DEAD_LETTER_TOPIC=${TASK_SERVICE_DEAD_LETTER_TOPIC}
TASK_SERVICE_MAX_ATTEMPTS=${TASK_SERVICE_MAX_ATTEMPTS}
TASK_SERVICE_HELPER_LEASE_SECONDS=${TASK_SERVICE_HELPER_LEASE_SECONDS}
TASK_SERVICE_RETRY_BACKOFF_SECONDS=${TASK_SERVICE_RETRY_BACKOFF_SECONDS}
TASK_SERVICE_RECOVERY_ENABLED=${TASK_SERVICE_RECOVERY_ENABLED}
TASK_SERVICE_RECOVERY_POLL_SECONDS=${TASK_SERVICE_RECOVERY_POLL_SECONDS}
TASK_SERVICE_RECOVERY_BATCH_SIZE=${TASK_SERVICE_RECOVERY_BATCH_SIZE}
PROJECT_PLAN_REQUEST_TOPIC=${PROJECT_PLAN_REQUEST_TOPIC}
PROJECT_PLAN_RESULT_TOPIC=${PROJECT_PLAN_RESULT_TOPIC}
WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC=${WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC}
WORKFLOW_LOG_AUDIT_TOPIC=${WORKFLOW_LOG_AUDIT_TOPIC}
REDIS_TASK_STATUS_URL=${REDIS_TASK_STATUS_URL}
REDIS_TASK_STATUS_KEY_PREFIX=${REDIS_TASK_STATUS_KEY_PREFIX}
STORAGE_NODE_ROOT=${STORAGE_NODE_ROOT}
SQLITE_NODE_DATABASE_ROOT=${SQLITE_NODE_DATABASE_ROOT}
TASK_SERVICE_STATE_DB_PATH=${TASK_SERVICE_STATE_DB_PATH:-${RAG_LOCAL_DATA_DIR}/task_service_state.db}
EOF
}

bootstrap_broker_topics() {
  "$PYTHON_BIN" - <<'PY'
import asyncio

from broker_service import BrokerSettings, bootstrap_topics, broker_health, create_redpanda_admin


async def main() -> None:
    admin = create_redpanda_admin(BrokerSettings.from_values(dict(__import__("os").environ)))
    await admin.start()
    try:
        await bootstrap_topics(admin)
        health = await broker_health(admin)
    finally:
        await admin.stop()
    if not health.get("ok"):
        raise SystemExit(f"broker health failed: {health}")


asyncio.run(main())
PY
}

verify_redis_status() {
  "$PYTHON_BIN" - <<'PY'
import asyncio
import os
from uuid import uuid4

from redis_status_node import RedisStatusSettings, RedisTaskStatusStore, TaskStatusRecord


async def main() -> None:
    settings = RedisStatusSettings.from_values(dict(os.environ))
    store = RedisTaskStatusStore(settings=settings)
    task_id = f"startup-{uuid4().hex}"
    try:
        if not await store.ping():
            raise SystemExit("Redis ping returned false")
        await store.set_status(TaskStatusRecord(task_id=task_id, status="completed"), ttl_seconds=60)
        if await store.get_status(task_id) is None:
            raise SystemExit("Redis task status readback failed")
        ttl = await store.ttl(task_id)
        if ttl <= 0:
            raise SystemExit(f"Redis task status TTL was not set: {ttl}")
    finally:
        await store.client.aclose()


asyncio.run(main())
PY
}

verify_broker_first_readiness() {
  local skip_qdrant="${1:-0}"
  if [[ "$skip_qdrant" -eq 1 ]]; then
    "$PYTHON_BIN" -m deployment.composition.readiness --skip-qdrant
  else
    "$PYTHON_BIN" -m deployment.composition.readiness
  fi
}

start_module_background() {
  local label="$1"
  local module="$2"
  local pid_file="$3"
  local log_name="$4"
  local worker_log="${LOG_DIR}/${log_name}.log"
  : > "$worker_log"
  if command -v setsid >/dev/null 2>&1; then
    setsid bash -c 'exec "$PYTHON_BIN" -m "$1"' _ "$module" > "$worker_log" 2>&1 &
  else
    "$PYTHON_BIN" -m "$module" > "$worker_log" 2>&1 &
  fi
  local pid=$!
  echo "$pid" > "$pid_file"
  sleep 2
  if ! is_pid_alive "$pid"; then
    echo "${label} failed to stay running. Log follows:" >&2
    sed -n '1,160p' "$worker_log" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  echo "${label} started with PID ${pid}. Log: ${worker_log}"
}

start_broker_first_background() {
  start_module_background "Redis status node" "redis_status_node.worker" "$REDIS_STATUS_PID_FILE" "redis-status"
  start_module_background "SQLite node" "sqlite_node.worker" "$SQLITE_NODE_PID_FILE" "sqlite-node"
  start_module_background "Storage node" "storage_node.worker" "$STORAGE_NODE_PID_FILE" "storage-node"
  start_module_background "Task manager" "task_manager_service.worker" "$TASK_MANAGER_PID_FILE" "task-manager"
  start_module_background "Task service" "task_service.worker" "$TASK_SERVICE_PID_FILE" "task-service"
  start_module_background "Project planning service" "project_service.domain_app" "$PROJECT_SERVICE_PID_FILE" "project-service"
  start_module_background "Workflow log service" "workflow_log_service.worker" "$WORKFLOW_LOG_PID_FILE" "workflow-log"
  start_module_background "Ingestion helper" "ingestion_service.server.worker" "$INGESTION_WORKER_PID_FILE" "ingestion-worker"
  start_module_background "Retrieval helper" "retrieval_service.server.worker" "$RETRIEVAL_WORKER_PID_FILE" "retrieval-worker"
  start_module_background "Retrieval index helper" "retrieval_service.indexing.worker" "$RETRIEVAL_INDEX_WORKER_PID_FILE" "retrieval-index-worker"
}

run_end_to_end_smoke() {
  echo "Running local health, ingest, and strict search smoke checks..."
  RAG_TEST_PROJECT_ID="$PROJECT_ID" \
    RAG_TEST_TIMEOUT_SECONDS=90 \
    "$PYTHON_BIN" -m examples.test_client.test_1
  RAG_TEST_PROJECT_ID="$PROJECT_ID" \
    RAG_TEST_TIMEOUT_SECONDS=90 \
    "$PYTHON_BIN" -m examples.test_client.test_2 \
      --doc-id local_startup_smoke \
      --max-attempts 90
  RAG_TEST_PROJECT_ID="$PROJECT_ID" \
    RAG_TEST_TIMEOUT_SECONDS=90 \
    "$PYTHON_BIN" -m examples.test_client.test_3 \
      --doc-id local_startup_smoke \
      --require-chunks
  echo "Local end-to-end smoke checks passed."
}

cleanup_failed_startup() {
  local exit_code=$?
  trap - ERR
  echo "Local startup failed; stopping processes started by this runner. Logs remain under ${LOG_DIR}." >&2
  "$SCRIPT_DIR/stop-all.sh" >/dev/null 2>&1 || true
  exit "$exit_code"
}

validate_provider_config
validate_runtime_config

if [[ "$START_SERVER" -eq 1 ]]; then
  check_runtime_dependencies
  start_broker_if_needed
  start_redis_if_needed
  start_redpanda_console_if_needed
  start_redis_insight_if_needed
  bootstrap_broker_topics
  verify_redis_status
  verify_broker_first_readiness 1
  if [[ "$INFRA_ONLY" -eq 1 ]]; then
    write_state
    echo "Broker infrastructure is ready."
    echo "Run live smoke tests with: RAG_LIVE_INFRA=1 pytest -m live_infra tests/integration/test_live_infra_smoke.py"
    exit 0
  fi
  start_qdrant_if_needed
  verify_broker_first_readiness 0
  ensure_not_already_running
fi

if [[ "$INIT_PROJECT" -eq 1 ]]; then
  init_project_config
fi

write_state

cat <<EOF
Local RAG service settings:
  project_id:          ${PROJECT_ID}
  project_type:        ${PROJECT_TYPE}
  runtime_dir:         ${RUNTIME_DIR}
  data_dir:            ${RAG_LOCAL_DATA_DIR}
  config_profile:      ${RAG_CONFIG_PROFILE}
  project_config_db:   ${PROJECT_CONFIG_DB_PATH}
  response_cache_db:   ${RAG_RESPONSE_CACHE_DB_PATH}
  ingestion_job_db:    ${INGESTION_JOB_DB_PATH}
  workflow_log_db:     ${WORKFLOW_LOG_DB_PATH}
  placement_db:        ${RETRIEVAL_PLACEMENT_DB_PATH}
  placement_mode:      ${RETRIEVAL_PLACEMENT_ROUTING_MODE}
  grpc_port:           ${RAG_GRPC_PORT}
  qdrant:              ${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}
  broker_type:         ${BROKER_TYPE}
  broker:              ${BROKER_BOOTSTRAP_SERVERS}
  broker_topic_prefix: ${BROKER_TOPIC_PREFIX}
  redpanda_console:    http://127.0.0.1:${REDPANDA_CONSOLE_PORT} $([[ "$START_REDPANDA_CONSOLE" -eq 1 ]] && printf '(enabled)' || printf '(disabled)')
  redis_insight:       http://127.0.0.1:${REDIS_INSIGHT_PORT} $([[ "$START_REDIS_INSIGHT" -eq 1 ]] && printf '(enabled)' || printf '(disabled)')
  task_intake_topic:   ${MANAGER_TASK_INTAKE_TOPIC}
  task_manager:        ${TASK_MANAGER_SERVICE_NAME}
  task_service:        ${TASK_SERVICE_NAME}
  task_requests:       ${TASK_SERVICE_TASK_REQUEST_TOPIC}
  task_dead_letters:   ${TASK_SERVICE_DEAD_LETTER_TOPIC}
  task_max_attempts:   ${TASK_SERVICE_MAX_ATTEMPTS}
  task_helper_lease_s: ${TASK_SERVICE_HELPER_LEASE_SECONDS}
  task_retry_backoff_s:${TASK_SERVICE_RETRY_BACKOFF_SECONDS}
  task_recovery:       ${TASK_SERVICE_RECOVERY_ENABLED}
  project_plans:       ${PROJECT_PLAN_REQUEST_TOPIC} -> ${PROJECT_PLAN_RESULT_TOPIC}
  workflow_log:        ${WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC} + ${WORKFLOW_LOG_AUDIT_TOPIC}
  redis_status:        ${REDIS_TASK_STATUS_URL}
  ingestion_helper:    ${INGESTION_HELPER_COMMAND_TOPIC}
  retrieval_helper:    ${RETRIEVAL_HELPER_COMMAND_TOPIC}
  index_helper:        ${RETRIEVAL_INDEX_HELPER_COMMAND_TOPIC}
  storage_node_root:   ${STORAGE_NODE_ROOT}
  sqlite_node_root:    ${SQLITE_NODE_DATABASE_ROOT}
  embedding_provider:  ${RAG_EMBEDDING_PROVIDER}
  embedding_model:     ${RAG_EMBEDDING_MODEL}
  embedding_dimension: ${RAG_EMBEDDING_DIMENSION}
  embedding_version:   ${RAG_EXAMPLE_EMBEDDING_VERSION:-v1}
EOF

if [[ "$START_SERVER" -eq 0 ]]; then
  echo "Setup complete; services were not started because --no-server was set."
  exit 0
fi

if [[ "$FOREGROUND" -eq 1 ]]; then
  trap cleanup_failed_startup ERR
  start_broker_first_background
  manager_log="${LOG_DIR}/manager.log"
  : > "$manager_log"
  echo "Starting manager in foreground. Log: ${manager_log}"
  echo "Press Ctrl-C to stop; then run examples/local/stop-all.sh for cleanup."
  trap - ERR
  exec "$PYTHON_BIN" -m manager_service.worker 2>&1 | tee -a "$manager_log"
fi

trap cleanup_failed_startup ERR
start_broker_first_background
start_module_background "Manager" "manager_service.worker" "$MANAGER_PID_FILE" "manager"
manager_pid="$(cat "$MANAGER_PID_FILE")"
wait_for_service_port \
  "Manager" \
  "$manager_pid" \
  "127.0.0.1" \
  "$RAG_GRPC_PORT" \
  "${LOG_DIR}/manager.log" \
  90
echo "Manager gRPC ready at 127.0.0.1:${RAG_GRPC_PORT}."
if [[ "$RUN_SMOKE" -eq 1 ]]; then
  run_end_to_end_smoke
fi
trap - ERR
echo "Stop everything with: examples/local/stop-all.sh"
