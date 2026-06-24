# Implementation Documentation

This directory documents implemented subsystems. These files are closer to the
code than the design documents under `docs/design/`: they describe the current
runtime shape, important classes, configuration keys, test coverage, and known
operational constraints.

## Implemented Areas

- [Qdrant Sparse Retrieval](qdrant-sparse-retrieval.md)
- [Broker-First Message Foundation](broker-first-message-foundation.md)
- [Retrieval Runtime Configuration](retrieval-runtime-configuration.md)
- [Sparse Retrieval Testing And Showcase](sparse-retrieval-testing-and-showcase.md)

## Current Retrieval Position

The retrieval stack supports three project-level modes:

- `dense`: embedding query against Qdrant dense vectors.
- `bm25`: FastEmbed sparse query against a named Qdrant sparse vector.
- `hybrid`: dense and sparse candidate retrieval, union, fusion, optional entity
  boost, and optional reranking.

BM25-style retrieval is implemented through Qdrant sparse vectors. There is no
SQLite FTS5 sidecar index in the current retrieval design.

## Main Code Paths

```text
project_service/rag/engine.py
project_service/rag/retrieval_config.py
project_service/rag/retriever_factory.py
project_service/rag/cache_keys.py

retrieval_service/services/retriever.py
retrieval_service/services/bm25.py
retrieval_service/services/hybrid.py
retrieval_service/services/sparse_encoder.py
retrieval_service/services/vector_store.py

configs/config.py
configs/retrieval/config.py
project_service/server/app.py
```

## Verification

The sparse retrieval implementation is covered by:

```bash
python -m pytest tests/test_sparse_retrieval.py -q
python -m pytest -q
```

The showcase entrypoint is:

```bash
python -m examples.unites.rag_multi_retrieval_showcase
```
