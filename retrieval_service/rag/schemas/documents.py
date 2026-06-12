"""Compatibility shim for project document schemas."""

from project_service.schemas.documents import (
    ProjectChunk,
    ProjectChunkPayload,
    ProjectDocument,
)

BaseDocument = ProjectDocument
BaseChunk = ProjectChunk
BaseChunkPayload = ProjectChunkPayload

__all__ = [
    "BaseChunk",
    "BaseChunkPayload",
    "BaseDocument",
    "ProjectChunk",
    "ProjectChunkPayload",
    "ProjectDocument",
]
