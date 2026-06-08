"""Service package.

Import heavy services from their leaf modules:

- ``retrieval_service.services.vector_store`` for Qdrant
- ``retrieval_service.services.embedding`` for sentence-transformer embeddings
- ``retrieval_service.services.reranker`` for cross-encoder reranking

This module intentionally stays lightweight.
"""

__all__: list[str] = []
