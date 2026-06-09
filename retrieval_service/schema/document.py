"""Compatibility shim for document schemas."""

from project_service.schemas import (
    ProjectChunk as BaseChunk,
    ProjectChunkPayload as BaseChunkPayload,
    ProjectDocument as BaseDocument,
)

__all__ = ["BaseChunk", "BaseChunkPayload", "BaseDocument"]
