#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${RAG_LOCAL_RUNTIME_DIR:-${ROOT_DIR}/.run}"
LOG_DIR="${RUNTIME_DIR}/logs"
STATE_FILE="${RUNTIME_DIR}/state.env"
MANAGER_PID_FILE="${RUNTIME_DIR}/manager.pid"
PROJECT_SERVICE_PID_FILE="${RUNTIME_DIR}/project-service.pid"
INGESTION_WORKER_PID_FILE="${RUNTIME_DIR}/ingestion-worker.pid"
QDRANT_CID_FILE="${RUNTIME_DIR}/qdrant.cid"
QDRANT_LOG_PID_FILE="${RUNTIME_DIR}/qdrant-log.pid"
ENV_FILE="${RAG_LOCAL_ENV_FILE:-${SCRIPT_DIR}/local.env}"

INIT_PROJECT=0
RESET_FIRST=0
START_QDRANT=auto
FOREGROUND=0
START_SERVER=1
EXTERNAL_INGESTION=0
EXTERNAL_PROJECT_SERVICE=0
PROJECT_ID="${RAG_EXAMPLE_PROJECT_ID:-demo}"
PROJECT_TYPE="${RAG_EXAMPLE_PROJECT_TYPE:-website}"
QDRANT_CONTAINER="${RAG_QDRANT_CONTAINER:-qdrant-rag-local}"
QDRANT_VOLUME="${RAG_QDRANT_VOLUME:-qdrant-rag-local-data}"

usage() {
  cat <<'EOF'
Usage:
  examples/local/run-all.sh [options]

Starts the local multi-service composition:
  - Qdrant container, when Docker is available and Qdrant is not already reachable
  - manager gRPC server
  - project service, ingestion consumer, and workflow-log app composed behind manager

Options:
  --init                         Initialize/seed local project config.
  --reset                        Stop existing local services before starting.
  --foreground                   Run manager in the foreground after setup.
  --no-server                    Run setup/init only; do not start services.
  --external-ingestion           Start ingestion worker as a separate process.
  --external-project-service     Start project/RAG service as a separate process.
  --split-services               Shortcut for --external-project-service --external-ingestion.
  --env-file PATH                Source extra env vars before starting.
  --project-id VALUE             Project ID for --init. Default: demo.
  --project-type VALUE           Project type for --init. Default: website.
  --grpc-port VALUE              Manager gRPC port. Default: 50051.
  --project-grpc-port VALUE      Project service gRPC port. Default: 50052.
  --embedding-provider VALUE     local, openrouter, or remote. Default: local.
  --embedding-model VALUE        Embedding model name.
  --embedding-dimension VALUE    Embedding vector dimension. Default: 768.
  --qdrant                       Require/start local Docker Qdrant.
  --no-qdrant                    Do not try to start Qdrant.
  --qdrant-container VALUE       Docker container name. Default: qdrant-rag-local.
  --generation                   Enable optional generation client wiring.
  --help                         Show this help.

Examples:
  examples/local/run-all.sh --init
  examples/local/run-all.sh --reset --init --grpc-port 50051
  examples/local/run-all.sh --reset --init --split-services
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
    --external-ingestion)
      EXTERNAL_INGESTION=1
      shift
      ;;
    --external-project-service)
      EXTERNAL_PROJECT_SERVICE=1
      shift
      ;;
    --split-services)
      EXTERNAL_PROJECT_SERVICE=1
      EXTERNAL_INGESTION=1
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
    --project-grpc-port)
      export RAG_PROJECT_GRPC_PORT="${2:?--project-grpc-port requires a value}"
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

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export RAG_LOCAL_DATA_DIR="${RAG_LOCAL_DATA_DIR:-${SCRIPT_DIR}/.data}"
export RAG_CONFIG_DB_PATH="${RAG_CONFIG_DB_PATH:-${RAG_LOCAL_DATA_DIR}/config.db}"
export RAG_RESPONSE_CACHE_DB_PATH="${RAG_RESPONSE_CACHE_DB_PATH:-${RAG_LOCAL_DATA_DIR}/response_cache.db}"
export RAG_INGEST_JOB_DB_PATH="${RAG_INGEST_JOB_DB_PATH:-${RAG_LOCAL_DATA_DIR}/ingestion_jobs.db}"
export WORKFLOW_LOG_DB_PATH="${WORKFLOW_LOG_DB_PATH:-${RAG_LOCAL_DATA_DIR}/workflow_log.db}"
export RAG_OBJECT_STORAGE_BASE_PATH="${RAG_OBJECT_STORAGE_BASE_PATH:-${RAG_LOCAL_DATA_DIR}/raw_storage}"
export RAG_GRPC_PORT="${RAG_GRPC_PORT:-50051}"
export RAG_PROJECT_GRPC_PORT="${RAG_PROJECT_GRPC_PORT:-50052}"
export RAG_QDRANT_HOST="${RAG_QDRANT_HOST:-localhost}"
export RAG_QDRANT_PORT="${RAG_QDRANT_PORT:-6333}"
export RAG_QDRANT_GRPC_PORT="${RAG_QDRANT_GRPC_PORT:-6334}"
export RAG_MAX_PER_PROJECT="${RAG_MAX_PER_PROJECT:-20}"
export RAG_MAX_PER_USER="${RAG_MAX_PER_USER:-5}"
export RAG_MAX_CONCURRENT_SEARCHES="${RAG_MAX_CONCURRENT_SEARCHES:-32}"
export RAG_MAX_CONCURRENT_INGEST_SCHEDULES="${RAG_MAX_CONCURRENT_INGEST_SCHEDULES:-32}"
export RAG_INGEST_WORKERS="${RAG_INGEST_WORKERS:-1}"
export RAG_INGEST_QUEUE_MAXSIZE="${RAG_INGEST_QUEUE_MAXSIZE:-100}"
export RAG_INGEST_EVENT_TOPIC="${RAG_INGEST_EVENT_TOPIC:-ingestion.events}"
export RAG_INGEST_EVENT_QUEUE_MAXSIZE="${RAG_INGEST_EVENT_QUEUE_MAXSIZE:-1000}"
export WORKFLOW_LOG_SERVICE_ENABLED="${WORKFLOW_LOG_SERVICE_ENABLED:-true}"
export WORKFLOW_LOG_TOPIC="${WORKFLOW_LOG_TOPIC:-ingestion.events}"
export MANAGER_INGEST_TOPIC="${MANAGER_INGEST_TOPIC:-ingestion.requests}"
export MANAGER_WORKFLOW_TOPIC="${MANAGER_WORKFLOW_TOPIC:-workflow.events}"
export MANAGER_LOCAL_QUEUE_MAXSIZE="${MANAGER_LOCAL_QUEUE_MAXSIZE:-1000}"
export MANAGER_INGESTION_WORKER_MODE="${MANAGER_INGESTION_WORKER_MODE:-embedded}"
export MANAGER_QUEUE_BROKER="${MANAGER_QUEUE_BROKER:-local}"
export MANAGER_QUEUE_DB_PATH="${MANAGER_QUEUE_DB_PATH:-${RAG_LOCAL_DATA_DIR}/ingestion_queue.db}"
export MANAGER_PROJECT_CLIENT_MODE="${MANAGER_PROJECT_CLIENT_MODE:-local}"
export MANAGER_PROJECT_GRPC_TARGET="${MANAGER_PROJECT_GRPC_TARGET:-localhost:${RAG_PROJECT_GRPC_PORT}}"
export INGESTION_QUEUE_BROKER="${INGESTION_QUEUE_BROKER:-sqlite}"
export INGESTION_QUEUE_DB_PATH="${INGESTION_QUEUE_DB_PATH:-${MANAGER_QUEUE_DB_PATH}}"
export INGESTION_REQUEST_TOPIC="${INGESTION_REQUEST_TOPIC:-${MANAGER_INGEST_TOPIC}}"
export INGESTION_QUEUE_MAXSIZE="${INGESTION_QUEUE_MAXSIZE:-${MANAGER_LOCAL_QUEUE_MAXSIZE}}"
export INGESTION_PROJECT_CLIENT_MODE="${INGESTION_PROJECT_CLIENT_MODE:-local}"
export INGESTION_PROJECT_GRPC_TARGET="${INGESTION_PROJECT_GRPC_TARGET:-${MANAGER_PROJECT_GRPC_TARGET}}"
export RAG_EMBEDDING_PROVIDER="${RAG_EMBEDDING_PROVIDER:-local}"
export RAG_EMBEDDING_MODEL="${RAG_EMBEDDING_MODEL:-BAAI/bge-base-en-v1.5}"
export RAG_EMBEDDING_DEVICE="${RAG_EMBEDDING_DEVICE:-cpu}"
export RAG_EMBEDDING_DIMENSION="${RAG_EMBEDDING_DIMENSION:-768}"
export RAG_EMBEDDING_BASE_URL="${RAG_EMBEDDING_BASE_URL:-https://openrouter.ai/api/v1/embeddings}"
export RAG_GENERATION_ENABLED="${RAG_GENERATION_ENABLED:-false}"

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

mkdir -p "$RUNTIME_DIR" "$LOG_DIR" "$RAG_LOCAL_DATA_DIR" "$RAG_OBJECT_STORAGE_BASE_PATH"

if [[ "$RESET_FIRST" -eq 1 ]]; then
  "${SCRIPT_DIR}/stop-all.sh" --clean || true
fi

cd "$ROOT_DIR"

is_qdrant_reachable() {
  command -v curl >/dev/null 2>&1 && \
    curl -fsS "http://${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}/collections" >/dev/null 2>&1
}

start_qdrant_if_needed() {
  local qdrant_log="${LOG_DIR}/qdrant.log"
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
  python - <<'PY'
import importlib.util
import os
import sys

required = {
    "grpc": "grpcio",
    "qdrant_client": "qdrant-client",
}
if os.environ.get("RAG_EMBEDDING_PROVIDER", "local").lower() == "local":
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
    local)
      ;;
    openrouter|remote|openai_compatible)
      if [[ -z "${RAG_EMBEDDING_API_KEY:-}" ]]; then
        echo "RAG_EMBEDDING_API_KEY is required for RAG_EMBEDDING_PROVIDER=${RAG_EMBEDDING_PROVIDER}." >&2
        exit 1
      fi
      ;;
    *)
      echo "RAG_EMBEDDING_PROVIDER must be one of: local, openrouter, remote, openai_compatible" >&2
      exit 1
      ;;
  esac
}

init_project_config() {
  PROJECT_ID="$PROJECT_ID" PROJECT_TYPE="$PROJECT_TYPE" python - <<'PY'
import asyncio
import os
from pathlib import Path

from project_service.config import SQLiteProjectConfigRepository
from project_service.schemas import ProjectConfig


async def main() -> None:
    project_id = os.environ["PROJECT_ID"]
    project_type = os.environ["PROJECT_TYPE"]
    repo = SQLiteProjectConfigRepository(Path(os.environ["RAG_CONFIG_DB_PATH"]))
    await repo.initialize()
    await repo.upsert_project(
        ProjectConfig(
            project_id=project_id,
            project_type=project_type,
            active_embedding_version="v1",
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


asyncio.run(main())
PY
}

is_pid_alive() {
  [[ -n "${1:-}" ]] && kill -0 "$1" >/dev/null 2>&1
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
  if [[ -f "$PROJECT_SERVICE_PID_FILE" ]]; then
    local old_project_pid
    old_project_pid="$(cat "$PROJECT_SERVICE_PID_FILE" 2>/dev/null || true)"
    if is_pid_alive "$old_project_pid"; then
      echo "Project service is already running with PID ${old_project_pid}. Use examples/local/stop-all.sh first." >&2
      exit 1
    fi
    rm -f "$PROJECT_SERVICE_PID_FILE"
  fi
}

write_state() {
  cat > "$STATE_FILE" <<EOF
ROOT_DIR=${ROOT_DIR}
RUNTIME_DIR=${RUNTIME_DIR}
RAG_LOCAL_DATA_DIR=${RAG_LOCAL_DATA_DIR}
RAG_GRPC_PORT=${RAG_GRPC_PORT}
RAG_PROJECT_GRPC_PORT=${RAG_PROJECT_GRPC_PORT}
RAG_QDRANT_HOST=${RAG_QDRANT_HOST}
RAG_QDRANT_PORT=${RAG_QDRANT_PORT}
RAG_QDRANT_GRPC_PORT=${RAG_QDRANT_GRPC_PORT}
QDRANT_CONTAINER=${QDRANT_CONTAINER}
QDRANT_VOLUME=${QDRANT_VOLUME}
EOF
}

start_project_service_background() {
  local project_log="${LOG_DIR}/project-service.log"
  : > "$project_log"
  if command -v setsid >/dev/null 2>&1; then
    setsid bash -c 'RAG_GRPC_PORT="$1" exec python -m project_service.server.app' _ "$RAG_PROJECT_GRPC_PORT" > "$project_log" 2>&1 &
  else
    RAG_GRPC_PORT="$RAG_PROJECT_GRPC_PORT" python -m project_service.server.app > "$project_log" 2>&1 &
  fi
  local pid=$!
  echo "$pid" > "$PROJECT_SERVICE_PID_FILE"
  sleep 2
  if ! is_pid_alive "$pid"; then
    echo "Project service failed to stay running. Log follows:" >&2
    sed -n '1,160p' "$project_log" >&2 || true
    rm -f "$PROJECT_SERVICE_PID_FILE"
    exit 1
  fi
  echo "Project/RAG gRPC service started with PID ${pid}. Log: ${project_log}"
}

start_ingestion_worker_background() {
  local worker_log="${LOG_DIR}/ingestion-worker.log"
  : > "$worker_log"
  if command -v setsid >/dev/null 2>&1; then
    setsid bash -c 'exec python -m ingestion_service.server.worker' > "$worker_log" 2>&1 &
  else
    python -m ingestion_service.server.worker > "$worker_log" 2>&1 &
  fi
  local pid=$!
  echo "$pid" > "$INGESTION_WORKER_PID_FILE"
  sleep 2
  if ! is_pid_alive "$pid"; then
    echo "Ingestion worker failed to stay running. Log follows:" >&2
    sed -n '1,160p' "$worker_log" >&2 || true
    rm -f "$INGESTION_WORKER_PID_FILE"
    exit 1
  fi
  echo "Ingestion worker server started with PID ${pid}. Log: ${worker_log}"
}

start_manager_background() {
  local manager_log="${LOG_DIR}/manager.log"
  : > "$manager_log"
  if command -v setsid >/dev/null 2>&1; then
    setsid bash -c 'exec python -m manager_service.server.app' > "$manager_log" 2>&1 &
  else
    python -m manager_service.server.app > "$manager_log" 2>&1 &
  fi
  local pid=$!
  echo "$pid" > "$MANAGER_PID_FILE"
  sleep 2
  if ! is_pid_alive "$pid"; then
    echo "Manager failed to stay running. Log follows:" >&2
    sed -n '1,160p' "$manager_log" >&2 || true
    rm -f "$MANAGER_PID_FILE"
    exit 1
  fi
  echo "Manager gRPC server started with PID ${pid}. Log: ${manager_log}"
}

if [[ "$START_SERVER" -eq 1 ]]; then
  if [[ "$EXTERNAL_PROJECT_SERVICE" -eq 1 ]]; then
    export MANAGER_PROJECT_CLIENT_MODE=grpc
    export MANAGER_PROJECT_GRPC_TARGET="localhost:${RAG_PROJECT_GRPC_PORT}"
    export INGESTION_PROJECT_CLIENT_MODE=grpc
    export INGESTION_PROJECT_GRPC_TARGET="${MANAGER_PROJECT_GRPC_TARGET}"
  fi
  if [[ "$EXTERNAL_INGESTION" -eq 1 ]]; then
    export MANAGER_INGESTION_WORKER_MODE=external
    export MANAGER_QUEUE_BROKER=sqlite
    export INGESTION_QUEUE_BROKER=sqlite
  fi
  start_qdrant_if_needed
  validate_provider_config
  check_runtime_dependencies
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
  config_db:           ${RAG_CONFIG_DB_PATH}
  response_cache_db:   ${RAG_RESPONSE_CACHE_DB_PATH}
  ingest_jobs_db:      ${RAG_INGEST_JOB_DB_PATH}
  workflow_log_db:     ${WORKFLOW_LOG_DB_PATH}
  grpc_port:           ${RAG_GRPC_PORT}
  project_grpc_port:   ${RAG_PROJECT_GRPC_PORT}
  qdrant:              ${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}
  ingestion_mode:      ${MANAGER_INGESTION_WORKER_MODE}
  queue_broker:        ${MANAGER_QUEUE_BROKER}
  queue_db:            ${MANAGER_QUEUE_DB_PATH}
  project_client_mode: ${MANAGER_PROJECT_CLIENT_MODE}
  project_target:      ${MANAGER_PROJECT_GRPC_TARGET}
  embedding_provider:  ${RAG_EMBEDDING_PROVIDER}
  embedding_model:     ${RAG_EMBEDDING_MODEL}
  embedding_dimension: ${RAG_EMBEDDING_DIMENSION}
EOF

if [[ "$START_SERVER" -eq 0 ]]; then
  echo "Setup complete; services were not started because --no-server was set."
  exit 0
fi

if [[ "$FOREGROUND" -eq 1 ]]; then
  if [[ "$EXTERNAL_PROJECT_SERVICE" -eq 1 ]]; then
    start_project_service_background
  fi
  if [[ "$EXTERNAL_INGESTION" -eq 1 ]]; then
    start_ingestion_worker_background
  fi
  manager_log="${LOG_DIR}/manager.log"
  : > "$manager_log"
  echo "Starting manager in foreground. Log: ${manager_log}"
  echo "Press Ctrl-C to stop; then run examples/local/stop-all.sh for cleanup."
  exec python -m manager_service.server.app 2>&1 | tee -a "$manager_log"
fi

if [[ "$EXTERNAL_PROJECT_SERVICE" -eq 1 ]]; then
  start_project_service_background
fi
if [[ "$EXTERNAL_INGESTION" -eq 1 ]]; then
  start_ingestion_worker_background
fi
start_manager_background
echo "Stop everything with: examples/local/stop-all.sh"
