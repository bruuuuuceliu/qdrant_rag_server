#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INIT_PROJECT=0
START_SERVER=1
PROJECT_ID="${RAG_EXAMPLE_PROJECT_ID:-demo}"
PROJECT_TYPE="${RAG_EXAMPLE_PROJECT_TYPE:-website}"

usage() {
  cat <<'EOF'
Usage:
  deployment/local/start.sh [options]

Options:
  --init                 Seed the local project config before starting.
  --no-server            Run setup/init only; do not start the gRPC server.
  --project-id VALUE     Project ID to initialize. Default: demo.
  --project-type VALUE   Project type to initialize. Default: website.
  --grpc-port VALUE      gRPC port. Default: 50051.
  --embedding-provider VALUE
                         local, openrouter, or remote. Default: local.
  --embedding-model VALUE
                         Embedding model name.
  --embedding-dimension VALUE
                         Embedding vector dimension. Default: 768.
  --generation           Enable optional generation client wiring.
  --help                 Show this help.

Examples:
  deployment/local/start.sh --init
  deployment/local/start.sh --init --project-id demo
  deployment/local/start.sh --init --no-server
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --init)
      INIT_PROJECT=1
      shift
      ;;
    --no-server)
      START_SERVER=0
      shift
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

if [[ -f /home/bruce/miniconda3/etc/profile.d/conda.sh && "${CONDA_DEFAULT_ENV:-}" != "evo" ]]; then
  # shellcheck disable=SC1091
  source /home/bruce/miniconda3/etc/profile.d/conda.sh
  conda activate evo
fi

export RAG_CONFIG_DB_PATH="${RAG_CONFIG_DB_PATH:-/tmp/qdrant_rag/config.db}"
export RAG_RESPONSE_CACHE_DB_PATH="${RAG_RESPONSE_CACHE_DB_PATH:-/tmp/qdrant_rag/response_cache.db}"
export RAG_GRPC_PORT="${RAG_GRPC_PORT:-50051}"
export RAG_QDRANT_HOST="${RAG_QDRANT_HOST:-localhost}"
export RAG_QDRANT_PORT="${RAG_QDRANT_PORT:-6333}"
export RAG_MAX_PER_PROJECT="${RAG_MAX_PER_PROJECT:-20}"
export RAG_MAX_PER_USER="${RAG_MAX_PER_USER:-5}"
export RAG_INGEST_WORKERS="${RAG_INGEST_WORKERS:-2}"
export RAG_EMBEDDING_PROVIDER="${RAG_EMBEDDING_PROVIDER:-local}"
export RAG_EMBEDDING_MODEL="${RAG_EMBEDDING_MODEL:-BAAI/bge-base-en-v1.5}"
export RAG_EMBEDDING_DEVICE="${RAG_EMBEDDING_DEVICE:-cpu}"
export RAG_EMBEDDING_DIMENSION="${RAG_EMBEDDING_DIMENSION:-768}"
export RAG_EMBEDDING_BASE_URL="${RAG_EMBEDDING_BASE_URL:-https://openrouter.ai/api/v1/embeddings}"
export RAG_GENERATION_ENABLED="${RAG_GENERATION_ENABLED:-false}"

mkdir -p "$(dirname "$RAG_CONFIG_DB_PATH")" "$(dirname "$RAG_RESPONSE_CACHE_DB_PATH")"
cd "$ROOT_DIR"

if command -v curl >/dev/null 2>&1; then
  if ! curl -fsS "http://${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}/collections" >/dev/null 2>&1; then
    echo "Warning: Qdrant is not reachable at ${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}." >&2
    echo "Start it with: docker run --rm -p 6333:6333 -p 6334:6334 qdrant/qdrant" >&2
  fi
fi

case "${RAG_EMBEDDING_PROVIDER}" in
  local)
    ;;
  openrouter|remote)
    if [[ -z "${RAG_EMBEDDING_API_KEY:-}" ]]; then
      echo "RAG_EMBEDDING_API_KEY is required when RAG_EMBEDDING_PROVIDER=${RAG_EMBEDDING_PROVIDER}." >&2
      exit 1
    fi
    ;;
  *)
    echo "RAG_EMBEDDING_PROVIDER must be one of: local, openrouter, remote" >&2
    exit 1
    ;;
esac

if [[ "$INIT_PROJECT" -eq 1 ]]; then
  PROJECT_ID="$PROJECT_ID" PROJECT_TYPE="$PROJECT_TYPE" python - <<'PY'
import asyncio
import os
from pathlib import Path

from configs import SQLiteProjectConfigRepository
from retrieval_service.core import BaseProjectConfig


async def main() -> None:
    project_id = os.environ["PROJECT_ID"]
    project_type = os.environ["PROJECT_TYPE"]
    repo = SQLiteProjectConfigRepository(Path(os.environ["RAG_CONFIG_DB_PATH"]))
    await repo.initialize()
    await repo.upsert_project(
        BaseProjectConfig(
            project_id=project_id,
            project_type=project_type,
            active_embedding_version="v1",
            embedding_model=os.environ["RAG_EMBEDDING_MODEL"],
            reranker_model="none",
            retrieval_config={"candidate_count": 20, "top_k": 5},
        )
    )
    print(f"Initialized project {project_id!r} as type {project_type!r}")


asyncio.run(main())
PY
fi

cat <<EOF
Local retrieval server settings:
  project_id:         ${PROJECT_ID}
  config_db:          ${RAG_CONFIG_DB_PATH}
  response_cache_db:  ${RAG_RESPONSE_CACHE_DB_PATH}
  grpc_port:          ${RAG_GRPC_PORT}
  qdrant:             ${RAG_QDRANT_HOST}:${RAG_QDRANT_PORT}
  embedding_provider: ${RAG_EMBEDDING_PROVIDER}
  embedding_model:    ${RAG_EMBEDDING_MODEL}
  embedding_dimension:${RAG_EMBEDDING_DIMENSION}
  generation_enabled: ${RAG_GENERATION_ENABLED}
EOF

if [[ "$START_SERVER" -eq 0 ]]; then
  exit 0
fi

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
    print("Missing required runtime dependencies:", ", ".join(missing), file=sys.stderr)
    print('Install them with: python -m pip install -e ".[dev]"', file=sys.stderr)
    raise SystemExit(1)
PY

exec python -m server.app
