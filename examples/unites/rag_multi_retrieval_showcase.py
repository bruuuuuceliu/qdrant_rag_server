"""Showcase dense, BM25, and hybrid retrieval on one full document.

Setup:
1. Install dependencies: ``python -m pip install -e ".[sparse]"``
2. Start Qdrant: ``docker run --rm -p 6333:6333 -p 6334:6334 qdrant/qdrant``
   If Docker reports that port 6333 is already allocated, Qdrant is probably
   already running.
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
to collection version ``hybrid_v1`` so it does not collide with the simpler
``rag_insertion_retrieval`` example.


URL docs: https://grjvnhneekilmldvxcbg.supabase.co/storage/v1/object/public/howone/test_files/rag/oldmansea.pdf

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

from project_service.adapters.website import (  # noqa: E402
    WebsiteProjectAdapter,
    WebsiteProjectConfig,
)
from project_service.gateway import (  # noqa: E402
    IngestPlan,
    IngestRequest,
    SearchPlan,
    SearchRequest,
)
from project_service.rag import RagEngine  # noqa: E402
from retrieval_service.embedding import EmbeddingProviderFactory  # noqa: E402
from retrieval_service.services.bm25 import QdrantSparseBM25Index  # noqa: E402
from retrieval_service.services.sparse_encoder import FastEmbedSparseTextEncoder  # noqa: E402
from retrieval_service.services.vector_store import QdrantStore  # noqa: E402

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
    embedding_base_url = os.getenv(
        "RAG_EMBEDDING_BASE_URL",
        "https://openrouter.ai/api/v1/embeddings",
    )
    if embedding_provider_name == "openrouter" and not embedding_api_key:
        print("Set RAG_EMBEDDING_API_KEY for openrouter embeddings.")
        return

    embedding = EmbeddingProviderFactory.create(
        embedding_provider_name,
        model_name=embedding_model,
        device=os.getenv("RAG_EMBEDDING_DEVICE", "cpu"),
        api_key=embedding_api_key,
        base_url=embedding_base_url,
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
    engine = RagEngine(
        embedding_provider=embedding,
        qdrant_store=qdrant_store,
        bm25_index=bm25_index,
        sparse_encoder=sparse_encoder,
        ingest_worker_count=1,
    )

    adapter = WebsiteProjectAdapter()
    base_config = await adapter.get_config(project_id)
    ingest_config = _make_config(
        base_config=base_config,
        embedding_model=embedding_model,
        collection_version=collection_version,
        mode="hybrid",
    )

    try:
        ingest_result = await engine.schedule_ingest(
            IngestPlan(
                IngestRequest(
                    project_id,
                    user_id,
                    kb_id,
                    doc_id,
                    "https://example.com/retrieval-methods",
                    "text/plain",
                    {
                        "raw_text": FULL_DOCUMENT,
                        "page_title": "Retrieval Methods",
                    },
                ),
                adapter,
                ingest_config,
            )
        )
        await engine._ingest_queue.join()
        final_status = await engine.get_ingest_status(ingest_result.job_id)
        if final_status is None or final_status.error:
            error = final_status.error if final_status is not None else "unknown error"
            raise RuntimeError(f"showcase ingest failed: {error}")

        query = os.getenv(
            "RAG_MULTI_SHOWCASE_QUERY",
            os.getenv(
                "RAG_SHOWCASE_QUERY",
                "Which retrieval method is best for SKU-42 and exact error codes?",
            ),
        )
        for mode in ("dense", "bm25", "hybrid"):
            config = _make_config(
                base_config=base_config,
                embedding_model=embedding_model,
                collection_version=collection_version,
                mode=mode,
            )
            result = await _search(
                engine=engine,
                adapter=adapter,
                config=config,
                project_id=project_id,
                user_id=user_id,
                kb_id=kb_id,
                query=query,
            )
            print(f"\n=== {mode.upper()} search ===")
            for chunk in result.chunks:
                score = float(chunk["score"])
                print(f"{chunk['chunk_id']} score={score:.4f}: {chunk['text']}")
    finally:
        await engine.shutdown()
        await embedding.shutdown()
        await qdrant_store.close()


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


async def _search(
    *,
    engine: RagEngine,
    adapter: WebsiteProjectAdapter,
    config: WebsiteProjectConfig,
    project_id: str,
    user_id: str,
    kb_id: str,
    query: str,
):
    search_request = SearchRequest(project_id, user_id, query, (kb_id,))
    scope = await adapter.build_query_scope(search_request)
    retrieval_filter = await adapter.build_retrieval_filter(scope)
    return await engine.search(
        SearchPlan(search_request, adapter, config, scope, retrieval_filter)
    )


if __name__ == "__main__":
    asyncio.run(main())
