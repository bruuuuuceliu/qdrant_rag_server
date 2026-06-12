# Sparse Retrieval Testing And Showcase

## Test Coverage

The focused tests live in:

```text
tests/test_sparse_retrieval.py
```

Run them with:

```bash
python -m pytest tests/test_sparse_retrieval.py -q
```

The full suite is:

```bash
python -m pytest -q
```

## What The Focused Tests Cover

### Retrieval Config Parsing

The tests verify:

- `hybrid` settings parse correctly.
- `candidate_count` must be at least `top_k`.
- BM25 index version and NER settings are carried through typed settings.

### Qdrant Sparse BM25 Index

The tests verify that `QdrantSparseBM25Index.search()`:

- requires a sparse query vector.
- calls `QdrantStore.search_sparse()`.
- passes the configured sparse vector name.
- returns `RetrievalHit` objects with source `bm25`.

### Candidate Fusion

The tests verify that `CandidateFusion`:

- deduplicates by chunk ID.
- returns source `hybrid`.
- preserves retrieval source diagnostics.

### BM25 Search

The tests verify that BM25-only search:

- sparse-encodes the query.
- does not call the dense embedding provider.
- does not call dense Qdrant search.
- calls Qdrant sparse search.

### Hybrid Search

The tests verify that hybrid search:

- dense-encodes the query.
- sparse-encodes the query.
- calls dense Qdrant search.
- calls sparse Qdrant search.
- returns dense-only and sparse-only hits after fusion.

### Hybrid Ingest

The tests verify that hybrid ingest:

- dense-encodes chunk text.
- sparse-encodes chunk text.
- calls `QdrantStore.upsert_hybrid_points()`.
- does not call legacy dense-only `upsert()`.
- stores normalized sparse text in the configured payload field.

## Test Doubles

The focused tests intentionally use fakes:

- fake sparse encoder
- fake Qdrant points
- async mock Qdrant store

This keeps unit tests fast and deterministic. The tests validate contracts and
orchestration, not live Qdrant ranking behavior.

## Showcase

The runnable showcase is:

```text
examples/unites/rag_multi_retrieval_showcase.py
```

It ingests one full document using `mode="hybrid"` and then runs three searches:

- `dense`
- `bm25`
- `hybrid`

Run:

```bash
python -m examples.unites.rag_multi_retrieval_showcase
```

Required services and dependencies:

- Qdrant running locally or reachable through `RAG_QDRANT_URL`.
- Dense embedding provider configured.
- FastEmbed sparse dependency installed with `.[sparse]`.

Example setup:

```bash
python -m pip install -e ".[sparse]"
docker run --rm -p 6333:6333 -p 6334:6334 qdrant/qdrant

export RAG_QDRANT_HOST=localhost
export RAG_QDRANT_PORT=6333
export RAG_EMBEDDING_PROVIDER=local
export RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
export RAG_EMBEDDING_DIMENSION=768
export BM25_SPARSE_VECTOR_NAME=bm25
export BM25_DENSE_VECTOR_NAME=dense
export BM25_ENCODER_MODEL=Qdrant/bm25

python -m examples.unites.rag_multi_retrieval_showcase
```

## Expected Showcase Behavior

The showcase document contains semantic descriptions and exact lexical markers
such as:

```text
SKU-42
QDRANT_TIMEOUT
retrieval_config
```

Expected retrieval behavior:

- Dense search should retrieve semantically related chunks.
- BM25 search should favor chunks with exact lexical overlap.
- Hybrid search should include both semantic and exact-match candidates.

## Verification Commands Used During Implementation

```bash
python -m pytest tests/test_sparse_retrieval.py -q
python -m pytest -q
python -m py_compile examples/unites/rag_multi_retrieval_showcase.py
git diff --check
```

At the time of implementation, the focused sparse tests passed and the full
test suite passed.
