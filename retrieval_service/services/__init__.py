"""Service package.

Import heavy services from their leaf modules:

- ``retrieval_service.services.vector_store`` for Qdrant
- ``retrieval_service.embedding`` for embedding providers
- ``retrieval_service.llm`` for LLM generation providers
- ``retrieval_service.services.reranker`` for cross-encoder reranking

This module intentionally stays lightweight.
"""

__all__: list[str] = []
