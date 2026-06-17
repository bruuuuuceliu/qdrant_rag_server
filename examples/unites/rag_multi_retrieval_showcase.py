"""Showcase dense, BM25, and hybrid retrieval through the manager boundary.

Uses ManagerService with a local queue broker, project-document client,
and bare engine search delegation — the same boundary the manager uses.

Setup:
1. Install dependencies: ``python -m pip install -e ".[sparse]"``
2. Start Qdrant: ``docker run --rm -p 6333:6333 -p 6334:6334 qdrant/qdrant``
3. Configure embeddings in ``examples/unites/.env`` or your shell.
   Local default:
       RAG_EMBEDDING_PROVIDER=local
       RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
       RAG_EMBEDDING_DIMENSION=768
   OpenRouter/remote example:
       RAG_EMBEDDING_PROVIDER=openrouter
       RAG_EMBEDDING_MODEL=openai/text-embedding-3-small
       RAG_EMBEDDING_DIMENSION=1536
       RAG_EMBEDDING_API_KEY=sk-or-...
4. Run: ``python -m examples.unites.rag_multi_retrieval_showcase``

The showcase uses ``RAG_MULTI_SHOWCASE_*`` environment variables and defaults
to collection version ``hybrid_v1``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from manager_service import ManagerService, ProjectDocumentClient  # noqa: E402
from manager_service.routing import ManagerRouter  # noqa: E402
from project_service.adapters.website import (  # noqa: E402
    WebsiteProjectAdapter,
    WebsiteProjectConfig,
)
from project_service.client import LocalProjectServiceClient  # noqa: E402
from project_service.config import SQLiteProjectConfigRepository  # noqa: E402
from project_service.gateway import (  # noqa: E402
    AsyncConcurrencyLimiter,
    IngestRequest,
    RagGateway,
    SearchPlan,
    SearchRequest,
)
from project_service.rag import RagEngine  # noqa: E402
from project_service.schemas import ProjectConfig  # noqa: E402
from retrieval_service.embedding import EmbeddingProviderFactory  # noqa: E402
from retrieval_service.services.bm25 import QdrantSparseBM25Index  # noqa: E402
from retrieval_service.services.sparse_encoder import FastEmbedSparseTextEncoder  # noqa: E402
from retrieval_service.services.vector_store import QdrantStore  # noqa: E402
from shared.queue import LocalQueueBroker  # noqa: E402

load_dotenv(Path(__file__).with_name(".env"))


FULL_DOCUMENT = """
Qdrant is a vector database used for semantic search. It stores dense embedding
vectors and payload metadata so retrieval can respect project, user, and
knowledge-base filters.

BM25 is a lexical retrieval method. It favors exact word overlap, so it is useful
for identifiers, model names, error codes, product SKUs, and uncommon technical
phrases.

Hybrid retrieval combines dense semantic search with BM25 sparse search. Dense
retrieval catches meaning and paraphrases. BM25 catches precise terms such as
SKU-42, QDRANT_TIMEOUT, and retrieval_config.

Named entity recognition can enrich chunks with people, organizations, products,
locations, or domain-specific terms. In this project, NER is optional and can be
used to boost entity overlap without hard-filtering search results.

The recommended first-stage pipeline is hybrid candidate retrieval followed by
one optional reranker pass. Reranking should happen after dense and BM25 results
are merged and deduplicated.
""".strip()


async def main() -> None:
    if importlib.util.find_spec("fastembed") is None:
        print(
            "fastembed is required for BM25/hybrid sparse retrieval.\n"
            'Install it with: python -m pip install -e ".[sparse]"'
        )
        return

    project_id = os.getenv("RAG_MULTI_SHOWCASE_PROJECT_ID", "multi_retrieval_project")
    user_id = os.getenv("RAG_MULTI_SHOWCASE_USER_ID", "multi_user_a")
    kb_id = os.getenv("RAG_MULTI_SHOWCASE_KB_ID", "multi_demo")
    doc_id = os.getenv("RAG_MULTI_SHOWCASE_DOC_ID", "retrieval_methods_full_doc")
    collection_version = os.getenv("RAG_MULTI_SHOWCASE_VERSION", "hybrid_v1")

    embedding_provider_name = os.getenv("RAG_EMBEDDING_PROVIDER", "local")
    embedding_model = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
    embedding_dimension = int(os.getenv("RAG_EMBEDDING_DIMENSION", "768"))
    embedding_api_key = os.getenv("RAG_EMBEDDING_API_KEY") or os.getenv(
        "RAG_GENERATION_API_KEY", ""
    )
    if embedding_provider_name == "openrouter" and not embedding_api_key:
        print("Set RAG_EMBEDDING_API_KEY for openrouter embeddings.")
        return

    # --- Bootstrap service components ---------------------------------------

    config_db = Path("/tmp/qdrant_rag_multi_showcase_config.db")
    config_repo = SQLiteProjectConfigRepository(config_db)
    await config_repo.initialize()
    await config_repo.upsert_project(
        ProjectConfig(
            project_id=project_id,
            project_type="website",
            active_embedding_version=collection_version,
            embedding_model=embedding_model,
            reranker_model="bge-reranker-base",
            retrieval_config={
                "mode": "hybrid",
                "top_k": 3,
                "candidate_count": 8,
                "fusion": "rrf",
            },
        )
    )
    print(f"Seeded project config for {project_id}")

    adapter = WebsiteProjectAdapter(config_repo=config_repo)

    embedding = EmbeddingProviderFactory.create(
        embedding_provider_name,
        model_name=embedding_model,
        device=os.getenv("RAG_EMBEDDING_DEVICE", "cpu"),
        api_key=embedding_api_key,
        base_url=os.getenv(
            "RAG_EMBEDDING_BASE_URL",
            "https://openrouter.ai/api/v1/embeddings",
        ),
    )
    await embedding.initialize()

    qdrant_store = QdrantStore(
        url=os.getenv("RAG_QDRANT_URL") or None,
        host=os.getenv("RAG_QDRANT_HOST", "localhost"),
        port=int(os.getenv("RAG_QDRANT_PORT", "6333")),
        default_vector_size=embedding_dimension,
    )
    sparse_vector_name = os.getenv("BM25_SPARSE_VECTOR_NAME", "bm25")
    sparse_encoder = FastEmbedSparseTextEncoder(
        os.getenv("BM25_ENCODER_MODEL", "Qdrant/bm25")
    )
    bm25_index = QdrantSparseBM25Index(
        store=qdrant_store,
        sparse_vector_name=sparse_vector_name,
    )
    await bm25_index.initialize()

    gateway = RagGateway(
        adapter_resolver=_FakeResolver(adapter),
        concurrency_limiter=AsyncConcurrencyLimiter(
            max_per_project=10,
            max_per_user=5,
        ),
    )

    engine = RagEngine(
        embedding_provider=embedding,
        qdrant_store=qdrant_store,
        bm25_index=bm25_index,
        sparse_encoder=sparse_encoder,
        ingest_worker_count=1,
    )

    project_client: ProjectDocumentClient = LocalProjectServiceClient(
        gateway=gateway,
        engine=engine,
    )

    broker = LocalQueueBroker(maxsize=10)
    manager = ManagerService(
        project_documents=project_client,
        ingest_queue=broker,
        ingest_topic="ingestion.requests",
        ingest_response_timeout=30.0,
        router=ManagerRouter(ingest_topic="ingestion.requests"),
    )

    from ingestion_service.server.consumer import IngestionRequestConsumer
    consumer = IngestionRequestConsumer(
        queue=broker,
        project_documents=project_client,
        topic="ingestion.requests",
    )
    consumer.start()
    await asyncio.sleep(0.05)

    try:
        # --- Ingest through the manager (hybrid mode) -----------------------
        ingest_result = await manager.ingest(
            IngestRequest(
                project_id=project_id,
                user_id=user_id,
                kb_id=kb_id,
                doc_id=doc_id,
                source_uri="https://example.com/retrieval-methods",
                content_type="text/plain",
                raw_text=FULL_DOCUMENT,
                metadata={
                    "page_title": "Retrieval Methods",
                },
            )
        )
        print(f"Ingested {doc_id} → job_id={ingest_result.job_id} status={ingest_result.status}")

        # Wait for background processing
        await asyncio.sleep(0.5)

        # Check final status via the manager
        final_status = await manager.ingest_status(ingest_result.job_id)
        if final_status is None or getattr(final_status, "error", ""):
            error = getattr(final_status, "error", "unknown") if final_status else "unknown"
            raise RuntimeError(f"showcase ingest failed: {error}")
        print(f"Final status: {getattr(final_status, 'status', '?')}")

        # --- Search in each mode through the gateway + engine (for mode control) ---
        # Manager.search uses the default retrieval config. For mode-specific
        # search, we drop to the project client which uses the gateway directly.
        query = os.getenv(
            "RAG_MULTI_SHOWCASE_QUERY",
            "Which retrieval method is best for SKU-42 and exact error codes?",
        )
        base_config = await adapter.get_config(project_id)

        for mode in ("dense", "bm25", "hybrid"):
            config = _make_config(
                base_config=base_config,
                embedding_model=embedding_model,
                collection_version=collection_version,
                mode=mode,
            )
            search_request = SearchRequest(project_id, user_id, query, (kb_id,))
            scope = await adapter.build_query_scope(search_request)
            retrieval_filter = await adapter.build_retrieval_filter(scope)
            result = await engine.search(
                SearchPlan(search_request, adapter, config, scope, retrieval_filter)
            )
            print(f"\n=== {mode.upper()} search ===")
            for chunk in result.chunks:
                score = float(chunk["score"])
                print(f"  {chunk['chunk_id']} score={score:.4f}: {chunk['text']}")

    finally:
        await consumer.stop()
        await engine.shutdown()
        await embedding.shutdown()
        if bm25_index is not None:
            await bm25_index.close()
        await qdrant_store.close()


class _FakeResolver:
    def __init__(self, adapter: object) -> None:
        self._adapter = adapter

    async def resolve(self, project_id: str) -> object:
        del project_id
        return self._adapter


def _make_config(
    *,
    base_config: WebsiteProjectConfig,
    embedding_model: str,
    collection_version: str,
    mode: str,
) -> WebsiteProjectConfig:
    return replace(
        base_config,
        active_embedding_version=collection_version,
        embedding_model=embedding_model,
        retrieval_config={
            "mode": mode,
            "top_k": 3,
            "candidate_count": 8,
            "fusion": "rrf",
            "dense_weight": 0.7,
            "bm25_weight": 0.3,
            "bm25": {
                "sparse_vector_name": os.getenv("BM25_SPARSE_VECTOR_NAME", "bm25"),
                "dense_vector_name": os.getenv("BM25_DENSE_VECTOR_NAME", "dense"),
                "encoder_provider": "fastembed",
                "encoder_model": os.getenv("BM25_ENCODER_MODEL", "Qdrant/bm25"),
                "text_field": os.getenv("BM25_TEXT_FIELD", "text_lemmatized"),
                "lemmatize": True,
            },
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
