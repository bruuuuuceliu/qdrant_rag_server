#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${RAG_LOCAL_RUNTIME_DIR:-${ROOT_DIR}/.run}"
STATE_FILE="${RUNTIME_DIR}/state.env"
MANAGER_PID_FILE="${RUNTIME_DIR}/manager.pid"
PROJECT_SERVICE_PID_FILE="${RUNTIME_DIR}/project-service.pid"
INGESTION_WORKER_PID_FILE="${RUNTIME_DIR}/ingestion-worker.pid"
RETRIEVAL_INDEX_WORKER_PID_FILE="${RUNTIME_DIR}/retrieval-index-worker.pid"
RETRIEVAL_HTTP_PID_FILE="${RUNTIME_DIR}/retrieval-http.pid"
QDRANT_CID_FILE="${RUNTIME_DIR}/qdrant.cid"
QDRANT_LOG_PID_FILE="${RUNTIME_DIR}/qdrant-log.pid"

CLEAN_RUNTIME=0
CLEAN_DATA=0
STOP_DOCKER=1
FORCE=1
GRPC_PORT="${RAG_GRPC_PORT:-50051}"
PROJECT_GRPC_PORT="${RAG_PROJECT_GRPC_PORT:-50052}"
QDRANT_CONTAINER="${RAG_QDRANT_CONTAINER:-qdrant-rag-local}"
QDRANT_VOLUME="${RAG_QDRANT_VOLUME:-qdrant-rag-local-data}"
RAG_LOCAL_DATA_DIR="${RAG_LOCAL_DATA_DIR:-${SCRIPT_DIR}/.data}"

usage() {
  cat <<'EOF'
Usage:
  examples/local/stop-all.sh [options]

Stops local service tasks started by examples/local/run-all.sh. It first uses
PID/container state, then falls back to service-module process matching.

Options:
  --clean               Remove runtime files/logs after stopping.
  --clean-data          Remove local data directory after stopping.
  --no-docker           Do not stop/remove the local Qdrant container.
  --qdrant-container VALUE
                        Docker container name. Default: qdrant-rag-local.
  --grpc-port VALUE     Extra cleanup check for this gRPC port. Default: 50051.
  --project-grpc-port VALUE
                        Extra cleanup check for project gRPC port. Default: 50052.
  --no-force            Do not send SIGKILL if graceful stop times out.
  --help                Show this help.

Examples:
  examples/local/stop-all.sh
  examples/local/stop-all.sh --clean
  examples/local/stop-all.sh --clean --clean-data
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clean)
      CLEAN_RUNTIME=1
      shift
      ;;
    --clean-data)
      CLEAN_DATA=1
      shift
      ;;
    --no-docker)
      STOP_DOCKER=0
      shift
      ;;
    --qdrant-container)
      QDRANT_CONTAINER="${2:?--qdrant-container requires a value}"
      shift 2
      ;;
    --grpc-port)
      GRPC_PORT="${2:?--grpc-port requires a value}"
      shift 2
      ;;
    --project-grpc-port)
      PROJECT_GRPC_PORT="${2:?--project-grpc-port requires a value}"
      shift 2
      ;;
    --no-force)
      FORCE=0
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

if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
  GRPC_PORT="${RAG_GRPC_PORT:-$GRPC_PORT}"
  PROJECT_GRPC_PORT="${RAG_PROJECT_GRPC_PORT:-$PROJECT_GRPC_PORT}"
  QDRANT_CONTAINER="${QDRANT_CONTAINER:-qdrant-rag-local}"
  QDRANT_VOLUME="${QDRANT_VOLUME:-qdrant-rag-local-data}"
  RAG_LOCAL_DATA_DIR="${RAG_LOCAL_DATA_DIR:-${SCRIPT_DIR}/.data}"
fi

is_pid_alive() {
  [[ -n "${1:-}" ]] && kill -0 "$1" >/dev/null 2>&1
}

wait_for_exit() {
  local pid="$1"
  local seconds="${2:-10}"
  for _ in $(seq 1 "$seconds"); do
    if ! is_pid_alive "$pid"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

stop_pid() {
  local pid="$1"
  local label="$2"
  if ! is_pid_alive "$pid"; then
    return 0
  fi
  echo "Stopping ${label} PID ${pid}..."
  kill -TERM "-${pid}" >/dev/null 2>&1 || kill -TERM "$pid" >/dev/null 2>&1 || true
  if wait_for_exit "$pid" 10; then
    return 0
  fi
  if [[ "$FORCE" -eq 1 ]]; then
    echo "Force killing ${label} PID ${pid}..."
    kill -KILL "-${pid}" >/dev/null 2>&1 || kill -KILL "$pid" >/dev/null 2>&1 || true
    wait_for_exit "$pid" 5 || true
  fi
}

stop_pid_file() {
  local file="$1"
  local label="$2"
  if [[ ! -f "$file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    stop_pid "$pid" "$label"
  fi
  rm -f "$file"
}

fallback_stop_python_services() {
  local patterns=(
    "python -m local_runtime.manager_app"
    "python manager_service/server/app.py"
    "python -m ingestion_service.server.worker"
    "python -m retrieval_service.indexing.worker"
    "python -m retrieval_service.server.worker"
    "python -m project_service.server.app"
    "python project_service/server/app.py"
    "python -m server.app"
  )
  local pattern pid
  for pattern in "${patterns[@]}"; do
    if ! command -v pgrep >/dev/null 2>&1; then
      continue
    fi
    while read -r pid; do
      [[ -z "$pid" || "$pid" == "$$" ]] && continue
      stop_pid "$pid" "${pattern}"
    done < <(pgrep -f "$pattern" || true)
  done
}

fallback_stop_port_listener() {
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local pid command_line
  local port
  for port in "$GRPC_PORT" "$PROJECT_GRPC_PORT"; do
    while read -r pid; do
      [[ -z "$pid" || "$pid" == "$$" ]] && continue
      command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
      case "$command_line" in
        *local_runtime.manager_app*|*project_service.server.app*|*server.app*)
          stop_pid "$pid" "gRPC listener on port ${port}"
          ;;
      esac
    done < <(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  done
}

stop_qdrant() {
  if [[ "$STOP_DOCKER" -ne 1 ]] || ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  local container="$QDRANT_CONTAINER"
  if [[ -f "$QDRANT_CID_FILE" ]]; then
    container="$(cat "$QDRANT_CID_FILE" 2>/dev/null || echo "$container")"
  fi
  if [[ -n "$container" ]] && docker ps -a --format '{{.ID}} {{.Names}}' | grep -Eq "^${container}| ${QDRANT_CONTAINER}$"; then
    echo "Stopping Qdrant container ${QDRANT_CONTAINER}..."
    docker rm -f "$QDRANT_CONTAINER" >/dev/null 2>&1 || docker rm -f "$container" >/dev/null 2>&1 || true
  fi
  rm -f "$QDRANT_CID_FILE"
}

stop_pid_file "$INGESTION_WORKER_PID_FILE" "ingestion worker"
stop_pid_file "$RETRIEVAL_INDEX_WORKER_PID_FILE" "retrieval index worker"
stop_pid_file "$RETRIEVAL_HTTP_PID_FILE" "retrieval HTTP server"
stop_pid_file "$MANAGER_PID_FILE" "manager"
stop_pid_file "$PROJECT_SERVICE_PID_FILE" "project service"
stop_pid_file "$QDRANT_LOG_PID_FILE" "Qdrant log collector"
fallback_stop_python_services
fallback_stop_port_listener
stop_qdrant

if [[ "$CLEAN_RUNTIME" -eq 1 ]]; then
  rm -rf "$RUNTIME_DIR"
else
  rm -f "$STATE_FILE"
fi

if [[ "$CLEAN_DATA" -eq 1 ]]; then
  rm -rf "$RAG_LOCAL_DATA_DIR"
  if [[ "$STOP_DOCKER" -eq 1 ]] && command -v docker >/dev/null 2>&1; then
    docker volume rm "$QDRANT_VOLUME" >/dev/null 2>&1 || true
  fi
fi

echo "Local service cleanup complete."
