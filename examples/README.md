# Examples: Getting Started

This guide shows the shortest practical path to start the RAG platform and try ingest/search.

The project is now a multi-service RAG platform with a **manager service** at the edge routing requests to ingestion, retrieval, project, and workflow-log services. The manager coordinates work through typed service clients and async queue contracts.

## Architecture

```
Client → ManagerService → ManagerRouter → ProjectDocumentClient
       ↓                       ↓
  [ingestion_service]   [retrieval_service]
  [project_service]     [workflow_log_service]
  [memory_service]      [shared contracts & queue]
```

The `ManagerRouter` decides routing based on `operation` + `data_type`:

| operation | data_type | target |
|-----------|-----------|--------|
| ingest | project_document | ingestion_service |
| search | project_document | retrieval_service |
| delete | project_document | retrieval_service |
| status | project_document | ingestion_service |

## One-Line Local Start

From the repository root:

```bash
examples/local/run-all.sh --init
```

This command:

- stores local data under `examples/local/.data`
- starts Qdrant with Docker when needed and available
- initializes a demo project config when `--init` is provided
- starts the manager-owned gRPC app via `python -m manager_service.server.app`
- composes the project service, ingestion consumer, local queue, and workflow-log app behind the manager

Stop local services with:

```bash
examples/local/stop-all.sh --clean
```

Useful variants:

```bash
examples/local/run-all.sh --reset --init --project-id demo
examples/local/run-all.sh --init --no-server
examples/local/run-all.sh --init --grpc-port 50052
examples/local/run-all.sh --init --embedding-provider openrouter --embedding-model your-embedding-model --embedding-dimension 1536
examples/local/run-all.sh --init --generation
```

For remote/OpenRouter-compatible embeddings, provide an embedding API key:

```bash
export RAG_EMBEDDING_API_KEY=sk-or-your-key
examples/local/run-all.sh --init --embedding-provider openrouter --embedding-model your-embedding-model --embedding-dimension 1536
```

The older `deployment/local/start.sh` remains available for direct one-process startup, but `examples/local/` is the preferred showcase runner because it includes matching cleanup scripts and local runtime files.

## 1. Activate Environment

Use the project environment:

```bash
source /home/bruce/miniconda3/etc/profile.d/conda.sh
conda activate evo
```

Install the project:

```bash
python -m pip install -e ".[dev]"
```

## 2. Start Qdrant

If Docker is available:

```bash
docker run --rm -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

The default config expects Qdrant at `localhost:6333`.

## 3. Create Local Runtime Directories

For local development, use `/tmp` paths:

```bash
export RAG_CONFIG_DB_PATH=/tmp/qdrant_rag/config.db
export RAG_RESPONSE_CACHE_DB_PATH=/tmp/qdrant_rag/response_cache.db
export RAG_GRPC_PORT=50051
export RAG_QDRANT_HOST=localhost
export RAG_QDRANT_PORT=6333
export RAG_INGEST_WORKERS=1
export RAG_EMBEDDING_PROVIDER=local
export RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
export RAG_EMBEDDING_DEVICE=cpu
export RAG_EMBEDDING_DIMENSION=768
export RAG_GENERATION_ENABLED=false
```

## 4. Seed A Project Config

The manager resolves adapters from project config. Add a website project:

```bash
python - <<'PY'
import asyncio
import os
from pathlib import Path

from project_service.config import SQLiteProjectConfigRepository
from project_service.schemas import ProjectConfig

async def main():
    repo = SQLiteProjectConfigRepository(Path(os.environ["RAG_CONFIG_DB_PATH"]))
    await repo.initialize()
    await repo.upsert_project(
        ProjectConfig(
            project_id="demo",
            project_type="website",
            active_embedding_version="v1",
            embedding_model="BAAI/bge-base-en-v1.5",
            reranker_model="none",
            retrieval_config={"candidate_count": 20, "top_k": 5},
        )
    )

asyncio.run(main())
PY
```

## 5. Start The Server

```bash
python -m manager_service.server.app
```

On first start, the embedding model may take time to download/load. The manager app boots the manager, project service, ingestion consumer, and workflow log app behind a single gRPC entry point.

## 6. Ingest A Small Document

In another shell with the same environment activated:

```bash
python - <<'PY'
import asyncio
import grpc

from project_service.server.grpc.generated import retrieval_service_pb2, retrieval_service_pb2_grpc

async def main():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        client = retrieval_service_pb2_grpc.RagServiceStub(channel)
        response = await client.Ingest(
            retrieval_service_pb2.IngestRequest(
                project_id="demo",
                user_id="user_1",
                doc_id="hello_doc",
                source_uri="memory://hello_doc",
                content_type="text/plain",
                metadata={
                    "raw_text": "Hello world.\n\nThis service indexes chunks for retrieval.",
                },
            )
        )
        print(response)

asyncio.run(main())
PY
```

Save the returned `job_id`.

## 7. Check Ingest Status

```bash
python - <<'PY'
import asyncio
import grpc

from project_service.server.grpc.generated import retrieval_service_pb2, retrieval_service_pb2_grpc

JOB_ID = "replace-with-job-id"

async def main():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        client = retrieval_service_pb2_grpc.RagServiceStub(channel)
        response = await client.GetIngestJobStatus(
            retrieval_service_pb2.GetIngestJobStatusRequest(job_id=JOB_ID)
        )
        print(response)

asyncio.run(main())
PY
```

## 8. Search

```bash
python - <<'PY'
import asyncio
import grpc

from project_service.server.grpc.generated import retrieval_service_pb2, retrieval_service_pb2_grpc

async def main():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        client = retrieval_service_pb2_grpc.RagServiceStub(channel)
        response = await client.Search(
            retrieval_service_pb2.SearchRequest(
                project_id="demo",
                user_id="user_1",
                query="What does the service index?",
                include_shared=True,
            )
        )
        print(response)

asyncio.run(main())
PY
```

## Showcase Scripts

### Programmatic API via ManagerService (recommended)

Demonstrates using the `ManagerService` facade directly:

```bash
python -m examples.unites.rag_insertion_retrieval
```

This showcase:

- Creates a manager with a local queue broker and project client
- Ingests documents through the manager routing boundary
- Searches through the manager

### Standalone Ingestion

Tests the ingestion pipeline in isolation (no Qdrant, no embeddings):

```bash
python -m examples.unites.ingestion
```

### Multi-Retrieval Showcase

Ingests a full document in hybrid mode and compares dense, BM25, and hybrid search:

```bash
python -m examples.unites.rag_multi_retrieval_showcase
```

## 9. Optional Generation

Generation is disabled by default. To enable:

```bash
export RAG_GENERATION_ENABLED=true
```

Restart the server. Generation requests still require a request-scoped OpenRouter key in `GenerateRequest.openrouter_api_key`.

## Troubleshooting

### `ModuleNotFoundError: grpc` or Missing Runtime Dependencies

```bash
python -m pip install -e ".[dev]"
```

### Qdrant Connection Errors

```bash
curl http://localhost:6333/collections
```

### Search Returns No Results

- project config exists for `project_id`
- ingest job completed (`status=completed`)
- Qdrant is running
- `user_id` matches the ingested document
