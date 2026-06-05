"""Project-based RAG service package.

Import concrete components from their leaf modules, for example
``rag_server.core`` or ``rag_server.services.cache``.  The package root stays
lightweight so optional runtime dependencies such as Qdrant and model loaders
are imported only when those capabilities are used.
"""

__all__: list[str] = []
