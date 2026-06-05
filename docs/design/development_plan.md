# Development Plan Note

This older phase plan has been superseded by the current implementation plan and development documentation.

Use these documents instead:

- [Development](../development.md)
- [Configuration](../configuration.md)
- [Extension Guide](../extension-guide.md)
- [Current plan](../../details.md)
- [Current progress](../../progress.md)

Current next implementation order:

1. Make SQLite and filesystem persistence async-safe.
2. Add bounded durable ingest job repository.
3. Expose typed fields through gRPC/gateway.
4. Extend retrieval filters for data type, visibility, and versions.
5. Add retrieval framework for vector, BM25, hybrid, and rerank.
6. Add data-type registry.
7. Replace metadata raw content with typed raw content and collision-safe storage keys.
8. Add service-level batch ingest.
9. Make website adapter config-backed.
10. Clean up generation cache keys and prompt boundaries.
