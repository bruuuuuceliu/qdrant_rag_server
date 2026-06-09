# Qdrant Sparse Retrieval Implementation

## Purpose

This implementation adds BM25-style lexical retrieval to the existing dense
Qdrant retrieval path. Sparse retrieval is stored and queried inside Qdrant
using a named sparse vector, so dense and sparse representations live on the
same point.

Supported retrieval modes:

- `dense`: Qdrant dense vector search.
- `bm25`: Qdrant sparse vector search.
- `hybrid`: dense search plus sparse search, then candidate fusion.

There is no separate lexical database. Payload filters, point identities, delete
behavior, and collection ownership remain centered on Qdrant.

## Component Boundary

### `retrieval_service`

Low-level retrieval functionality lives here:

- `retrieval_service/services/retriever.py`
  Shared `RetrievalQuery`, `RetrievalHit`, `Retriever`, and dense Qdrant
  retriever.

- `retrieval_service/services/sparse_encoder.py`
  `SparseTextEncoder` protocol, `SparseVector` DTO, and
  `FastEmbedSparseTextEncoder`.

- `retrieval_service/services/bm25.py`
  `QdrantSparseBM25Index` and `BM25Retriever`.

- `retrieval_service/services/vector_store.py`
  Qdrant collection creation, dense upsert/search, hybrid dense+sparse upsert,
  and sparse search.

- `retrieval_service/services/hybrid.py`
  Candidate fusion and hybrid retriever.

### `project_service`

Project-level orchestration lives here:

- `project_service/rag/retrieval_config.py`
  Parses project `retrieval_config` into typed settings.

- `project_service/rag/retriever_factory.py`
  Selects dense, BM25, or hybrid retriever from project settings.

- `project_service/rag/engine.py`
  Encodes queries/chunks, calls Qdrant, applies optional NER boost and reranker.

- `project_service/rag/cache_keys.py`
  Includes retrieval mode, sparse vector name, encoder model, and index version
  in the search cache fingerprint.

## Collection Shape

Hybrid collections use one dense vector and one named sparse vector:

```python
vectors_config = {
    "dense": VectorParams(size=dense_vector_size, distance=Distance.COSINE)
}

sparse_vectors_config = {
    "bm25": SparseVectorParams(modifier=Modifier.IDF)
}
```

The default names are:

```text
dense vector name  = dense
sparse vector name = bm25
```

The sparse vector name is configurable per project and at runtime. The dense
vector name matters when searching a hybrid collection because Qdrant named
vectors require the query to specify which vector slot to use.

## Sparse Encoding

`FastEmbedSparseTextEncoder` lazily imports FastEmbed and uses
`Qdrant/bm25` by default.

```python
encoder = FastEmbedSparseTextEncoder("Qdrant/bm25")
query_sparse_vector = await encoder.encode("exact identifier SKU-42")
chunk_sparse_vectors = await encoder.encode_batch(chunk_texts)
```

The adapter returns the local `SparseVector` DTO:

```python
@dataclass(frozen=True, slots=True)
class SparseVector:
    indices: list[int]
    values: list[float]
```

`QdrantStore` converts this DTO into the Qdrant client sparse vector model at
the storage boundary.

## Ingest Flow

The ingest path is implemented in `RagEngine._run_ingest`.

```text
adapter.parse_document()
  -> adapter.build_chunks()
  -> optional NER enrichment
  -> adapter.build_payload()
  -> dense encode chunk text when dense is enabled
  -> sparse encode chunk text when bm25/hybrid is enabled
  -> QdrantStore.upsert_hybrid_points()
```

For `hybrid`, the engine upserts one Qdrant point per chunk with both vector
types:

```text
point id       deterministic from project/user/kb/doc/data_type/chunk/version
vector[dense]  dense embedding
vector[bm25]   sparse BM25 vector
payload        chunk text, scope fields, metadata, optional text_lemmatized
```

The sparse text is currently normalized by whitespace and case-folded when
`lemmatize=True`. The normalized value is stored in the payload field configured
by `bm25.text_field`, defaulting to `text_lemmatized`.

## Search Flow

The search path is implemented in `RagEngine.search`.

```text
parse retrieval_config
  -> build Qdrant payload filter from project scope
  -> dense encode query for dense/hybrid
  -> sparse encode query for bm25/hybrid
  -> build RetrievalQuery
  -> select retriever
  -> run search
  -> optional entity boost
  -> optional rerank
```

For `bm25`, `BM25Retriever` calls `QdrantSparseBM25Index.search`, which calls:

```python
await qdrant_store.search_sparse(
    collection_name=collection_name,
    sparse_vector_name="bm25",
    query_sparse_vector=query_sparse_vector,
    query_filter=qdrant_filter,
    limit=limit,
)
```

For `hybrid`, `HybridRetriever` runs dense and sparse retrievers concurrently
and passes both result sets into `CandidateFusion`.

## Fusion

Fusion is implemented in `retrieval_service/services/hybrid.py`.

Default method:

```text
rrf
```

RRF scoring:

```text
source_weight / (rrf_k + rank)
```

Deduplication keys:

```text
preferred key from FusionConfig
chunk_id
payload_id
project_id|user_id|kb_id|doc_id|chunk_index|text
```

The fused result keeps source diagnostics in:

```text
hit.metadata["retrieval_sources"]
hit.metadata["base_score"]
```

Reranking is intentionally outside `HybridRetriever`. The engine reranks once
after retrieval, fusion, and optional entity boost.

## Delete Behavior

Document delete calls Qdrant delete with project, user, KB, and document filters.
Because dense and sparse vectors live on the same point, no separate BM25 delete
path is required.

## Operational Notes

- Dense-only collections continue to support `dense` mode.
- `bm25` and `hybrid` require a collection with the named sparse vector slot.
- Existing dense-only collections should be reingested into a hybrid collection
  or migrated before enabling sparse retrieval.
- FastEmbed is optional at install time but required at runtime for `bm25` and
  `hybrid` modes.
- BM25 sparse scores and dense cosine scores are not directly comparable; use
  fusion or reranking rather than raw score mixing.

## Known Constraints

- The current `lemmatize=True` path performs normalization and case-folding, not
  full linguistic lemmatization.
- Unit tests use fake Qdrant and fake sparse encoders. They verify wiring and
  contracts, not live Qdrant ranking quality.
- Live sparse retrieval requires Qdrant sparse vector support and the FastEmbed
  sparse dependency.
