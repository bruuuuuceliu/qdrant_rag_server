# Retrieval Runtime Configuration

## Configuration Layers

Retrieval behavior is controlled in two places:

- Runtime environment settings configure available service components.
- Project `retrieval_config` selects retrieval behavior for a project/search.

Runtime settings are parsed in:

```text
configs/config.py
configs/retrieval/config.py
project_service/server/app.py
```

Project settings are parsed in:

```text
project_service/rag/retrieval_config.py
```

## Runtime Environment

Sparse retrieval runtime settings:

```env
BM25_SPARSE_VECTOR_NAME=bm25
BM25_DENSE_VECTOR_NAME=dense
BM25_ENCODER_PROVIDER=fastembed
BM25_ENCODER_MODEL=Qdrant/bm25
BM25_TEXT_FIELD=text_lemmatized
BM25_LEMMATIZE=true
BM25_INDEX_VERSION=qdrant_bm25_v1
```

NER runtime settings:

```env
RAG_NER_PROVIDER=disabled
RAG_NER_MODEL=en_core_web_sm
```

Embedding settings still control dense vector generation:

```env
RAG_EMBEDDING_PROVIDER=local
RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RAG_EMBEDDING_DEVICE=cpu
RAG_EMBEDDING_DIMENSION=768
```

## Runtime Wiring

`project_service/server/app.py` wires:

- `QdrantStore`
- dense embedding provider
- `FastEmbedSparseTextEncoder`
- `QdrantSparseBM25Index`
- optional local NER extractor
- `RagEngine`

The sparse encoder imports FastEmbed lazily. Creating the app does not download
or load the sparse model by itself; the model is loaded when `bm25` or `hybrid`
mode performs sparse encoding.

## Project Retrieval Config

Dense-only default:

```python
{
    "mode": "dense",
    "top_k": 5,
    "candidate_count": 20,
}
```

BM25-only:

```python
{
    "mode": "bm25",
    "top_k": 5,
    "candidate_count": 20,
    "bm25": {
        "sparse_vector_name": "bm25",
        "encoder_provider": "fastembed",
        "encoder_model": "Qdrant/bm25",
        "text_field": "text_lemmatized",
        "lemmatize": True,
        "index_version": "qdrant_bm25_v1",
    },
}
```

Hybrid:

```python
{
    "mode": "hybrid",
    "top_k": 5,
    "candidate_count": 40,
    "fusion": "rrf",
    "dense_weight": 0.7,
    "bm25_weight": 0.3,
    "bm25": {
        "sparse_vector_name": "bm25",
        "dense_vector_name": "dense",
        "encoder_provider": "fastembed",
        "encoder_model": "Qdrant/bm25",
        "text_field": "text_lemmatized",
        "lemmatize": True,
        "index_version": "qdrant_bm25_v1",
    },
}
```

NER boost:

```python
{
    "ner": {
        "enabled": True,
        "provider": "local",
        "model": "en_core_web_sm",
        "boost_entities": True,
        "entity_boost": 0.15,
        "enrichment_version": "ner_spacy_sm_v1",
    }
}
```

## Parsed Settings

Important parsed classes:

```python
ProjectRetrievalSettings
ProjectBM25Settings
ProjectNerSettings
```

Validation rules:

- `mode` must be `dense`, `bm25`, or `hybrid`.
- `fusion` must be `rrf` or `weighted`.
- `top_k` must be positive.
- `candidate_count` must be greater than or equal to `top_k`.
- `dense_weight` and `bm25_weight` must be non-negative.
- BM25 sparse vector name, dense vector name, encoder model, and text field must
  be non-empty.
- BM25 encoder provider currently must be `fastembed`.

## Cache Fingerprint

Search cache keys include retrieval settings through
`project_service/rag/cache_keys.py`.

The retrieval fingerprint includes:

- retrieval mode
- fusion method
- dense and BM25 weights
- sparse vector name
- dense vector name
- sparse encoder provider
- sparse encoder model
- sparse text payload field
- lemmatization flag
- sparse index version
- NER settings

This prevents dense-only cached results from being reused for BM25 or hybrid
queries.

## Installation Extras

Dense-only development:

```bash
python -m pip install -e ".[dev]"
```

Sparse retrieval runtime:

```bash
python -m pip install -e ".[sparse]"
```

Local NER runtime:

```bash
python -m pip install -e ".[ner]"
```

Combined local development:

```bash
python -m pip install -e ".[dev,sparse,ner]"
```

## Removed Configuration

The sparse retrieval implementation does not use these removed BM25 sidecar
settings:

```text
RAG_BM25_ENABLED
RAG_BM25_DB_PATH
BM25_BACKEND
```

BM25 retrieval is selected by project `retrieval_config.mode`, and the storage
path is Qdrant sparse vectors.
