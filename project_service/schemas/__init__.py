"""Project-RAG schema package."""

from project_service.schemas.cache import ProjectCacheScope
from project_service.schemas.config import ProjectConfig
from project_service.schemas.documents import (
    ProjectChunk,
    ProjectChunkPayload,
    ProjectDocument,
)
from project_service.schemas.jobs import ProjectIngestJob
from project_service.schemas.results import (
    GenerateResult,
    GenerationUnavailableError,
    IngestResult,
    SearchResult,
)
from project_service.schemas.scope import ProjectQueryScope, ProjectRetrievalFilter

# Project-RAG compatibility names. The neutral core Base* classes live in
# retrieval_service.core.schemas.
BaseDocument = ProjectDocument
BaseChunk = ProjectChunk
BaseChunkPayload = ProjectChunkPayload
BaseCacheScope = ProjectCacheScope
BaseIngestJob = ProjectIngestJob
BaseProjectConfig = ProjectConfig
BaseQueryScope = ProjectQueryScope
BaseRetrievalFilter = ProjectRetrievalFilter

__all__ = [
    "BaseChunk",
    "BaseChunkPayload",
    "BaseCacheScope",
    "BaseDocument",
    "BaseIngestJob",
    "BaseProjectConfig",
    "BaseQueryScope",
    "BaseRetrievalFilter",
    "GenerateResult",
    "GenerationUnavailableError",
    "IngestResult",
    "ProjectChunk",
    "ProjectChunkPayload",
    "ProjectCacheScope",
    "ProjectConfig",
    "ProjectDocument",
    "ProjectIngestJob",
    "ProjectQueryScope",
    "ProjectRetrievalFilter",
    "SearchResult",
]
