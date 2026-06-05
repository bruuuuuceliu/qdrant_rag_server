# Data Model

The current model is project-scoped and chunk-based.

## Hierarchy

```text
project_id
  -> active_embedding_version
    -> Qdrant collection rag_{project_id}_{active_embedding_version}
      -> user_id or __shared__
        -> kb_id
          -> doc_id
            -> chunk_id / chunk_index
```

## Default KB

`kb_id` is optional for callers.

If an ingest request omits `kb_id` or sends it blank, the service uses:

```text
default
```

Search requests use `kb_ids` only when the caller wants to restrict retrieval to selected knowledge bases. Blank search KB IDs are ignored.

## Core Models

### BaseProjectConfig

Project configuration:

```text
project_id
project_type
active_embedding_version
embedding_model
reranker_model
chunker_config
retrieval_config
cache_config
```

Collection name:

```text
rag_{project_id}_{active_embedding_version}
```

### BaseQueryScope

Search scope:

```text
project_id
user_id
kb_ids
include_shared
```

### BaseRetrievalFilter

Server-built retrieval filter:

```text
project_id
user_id
kb_ids
doc_ids
shared_user_id
```

When shared content is enabled, allowed user IDs are:

```text
{request_user_id, "__shared__"}
```

When shared content is disabled:

```text
{request_user_id}
```

### BaseDocument

Parsed source document:

```text
project_id
user_id
kb_id
doc_id
source_uri
content_type
data_type
visibility
content_hash
embedding_version
chunker_version
metadata
```

### BaseChunk

Chunk produced from a document:

```text
project_id
user_id
kb_id
doc_id
chunk_id
chunk_index
text
data_type
visibility
content_hash
embedding_version
chunker_version
metadata
```

### BaseChunkPayload

Payload stored beside the Qdrant vector:

```text
project_id
user_id
kb_id
doc_id
chunk_id
chunk_index
text
data_type
visibility
content_hash
embedding_version
chunker_version
metadata
```

## Qdrant Point Shape

Each Qdrant point has:

```text
id: deterministic UUID
vector: list[float]
payload: BaseChunkPayload as dict
```

Payload example:

```python
{
    "project_id": "p1",
    "user_id": "u1",
    "kb_id": "default",
    "doc_id": "doc_1",
    "chunk_id": "doc_1:0",
    "chunk_index": 0,
    "text": "The chunk text...",
    "data_type": "document",
    "visibility": "private",
    "content_hash": "",
    "embedding_version": "v1",
    "chunker_version": "v1",
    "metadata": {"section": "0"},
}
```

## Qdrant Point ID

Point IDs are deterministic UUIDs built from:

```text
project_id
user_id
kb_id
doc_id
data_type
chunk_index
chunker_version
```

This lets re-indexing the same logical chunk overwrite the existing point while avoiding collisions across users, KBs, data types, and chunker versions.

## Retrieval Filter

The engine builds Qdrant filters from `BaseRetrievalFilter`.

Current filter fields:

```text
project_id
user_id or user_id IN (...)
kb_id or kb_id IN (...)
doc_id or doc_id IN (...)
```

Planned filter fields:

```text
data_type or data_type IN (...)
visibility or visibility IN (...)
embedding_version or embedding_version IN (...)
chunker_version or chunker_version IN (...)
```

## Data Type Direction

The base model already carries `data_type`. The next step is a data-type registry so each data type can define:

- input schema
- validation rules
- parsing
- chunking
- payload fields
- retrieval filters
- default retrievers
- prompt strategy if generation is used
