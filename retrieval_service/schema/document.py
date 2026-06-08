"""Compatibility shim for document schemas."""

from retrieval_service.core.schemas.document import (
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
)

__all__ = ["BaseChunk", "BaseChunkPayload", "BaseDocument"]
