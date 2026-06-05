# Architecture Note

This older RAG-centered design document has been superseded by the current retrieval-first documentation.

Use these documents instead:

- [Overview](../overview.md)
- [Architecture](../architecture.md)
- [Data Model](../data-model.md)
- [Workflows](../workflows.md)
- [Extension Guide](../extension-guide.md)

The current design position is:

- The project is a minimal information retrieval service, not only a RAG server.
- Vector retrieval is implemented first, but BM25 and hybrid retrieval should fit behind the same retriever interface.
- Generation is optional and should use request-scoped provider keys.
- Components should be replaceable through narrow interfaces.
