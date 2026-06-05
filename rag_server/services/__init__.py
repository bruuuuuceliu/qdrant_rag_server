"""Service package.

Import heavy services from their leaf modules:

- ``rag_server.services.vector_store`` for Qdrant
- ``rag_server.services.embedding`` for sentence-transformer embeddings
- ``rag_server.services.reranker`` for cross-encoder reranking

This module intentionally stays lightweight.
"""

__all__: list[str] = []
