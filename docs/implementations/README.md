# Implementation Documentation

This directory documents implemented subsystems. These files are closer to the
code than the design documents under `docs/design/`: they describe the current
runtime shape, important classes, configuration keys, test coverage, and known
operational constraints.

## Implemented Areas

- [Broker-First Message Foundation](broker-first-message-foundation.md)

## Current Retrieval Position

The retrieval stack supports these project-level modes:

- `dense`: embedding query against Qdrant dense vectors.
- `bm25`: FastEmbed sparse query against a named Qdrant sparse vector.
- `hybrid`: dense and sparse candidate retrieval, union, fusion, optional entity
  boost, and optional reranking.

BM25-style retrieval is implemented through Qdrant sparse vectors. There is no
SQLite FTS5 sidecar index in the current retrieval design.

## Main Code Paths

```text
retrieval_service/services/retriever.py
retrieval_service/services/bm25.py
retrieval_service/services/hybrid.py
retrieval_service/services/sparse_encoder.py
retrieval_service/services/vector_store.py

configs/config.py
configs/retrieval/config.py
retrieval_service/retrieval/
retrieval_service/indexing/
```

## Verification

Run the full suite with:

```bash
python -m pytest -q
```
