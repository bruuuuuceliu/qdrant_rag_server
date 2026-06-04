"""Project-based RAG service core."""

from rag_server.core.models import (
    BaseCacheScope,
    BaseChunk,
    BaseChunkPayload,
    BaseDocument,
    BaseIngestJob,
    BaseProjectConfig,
    BaseQueryScope,
    BaseRetrievalFilter,
    IngestJobStatus,
    SHARED_USER_ID,
)
from rag_server.adapters.base import (
    AdapterNotFoundError,
    DuplicateAdapterError,
    ProjectAdapter,
    ProjectAdapterRegistry,
    ProjectAdapterResolver,
    ProjectTypeRepository,
)
from rag_server.config.repository import (
    ProjectConfigNotFoundError,
    ProjectConfigRecord,
    SQLiteProjectConfigRepository,
)
from rag_server.gateway.handler import (
    AsyncConcurrencyLimiter,
    ConcurrencyLimitExceededError,
    GatewayError,
    IngestPlan,
    IngestRequest,
    InvalidRequestError,
    ProjectScopeMismatchError,
    RagGateway,
    SearchPlan,
    SearchRequest,
)
from rag_server.services.embedding import EmbeddingService
from rag_server.services.vector_store import QdrantStore
from rag_server.engine.engine import RagEngine, SearchResult, IngestResult, GenerateResult
from rag_server.services.reranker import RerankerService
from rag_server.services.cache import Tier1MemoryCache, Tier2ResponseCache
from rag_server.services.generation import OpenRouterClient
from rag_server.health.health import HealthChecker, MetricsCollector
from rag_server.versioning.manager import VersionManager, VersionInfo, VersionNotFoundError
from rag_server.storage.base import (
    make_storage_key,
    ObjectStorage,
    ObjectStorageError,
)
from rag_server.storage.memory import MemoryObjectStorage
from rag_server.storage.filesystem import FilesystemObjectStorage
from rag_server.storage.s3 import S3ObjectStorage
from rag_server.adapters.website import (
    WebsiteChunkPayload,
    WebsiteDocument,
    WebsiteProjectAdapter,
    WebsiteProjectConfig,
)

__all__ = [
    "BaseCacheScope",
    "BaseChunk",
    "BaseChunkPayload",
    "BaseDocument",
    "BaseIngestJob",
    "BaseProjectConfig",
    "BaseQueryScope",
    "BaseRetrievalFilter",
    "IngestJobStatus",
    "SHARED_USER_ID",
    "AdapterNotFoundError",
    "DuplicateAdapterError",
    "ProjectAdapter",
    "ProjectAdapterRegistry",
    "ProjectAdapterResolver",
    "ProjectTypeRepository",
    "ProjectConfigNotFoundError",
    "ProjectConfigRecord",
    "SQLiteProjectConfigRepository",
    "AsyncConcurrencyLimiter",
    "ConcurrencyLimitExceededError",
    "GatewayError",
    "IngestPlan",
    "IngestRequest",
    "InvalidRequestError",
    "ProjectScopeMismatchError",
    "RagGateway",
    "SearchPlan",
    "SearchRequest",
    "EmbeddingService",
    "QdrantStore",
    "RagEngine",
    "SearchResult",
    "IngestResult",
    "GenerateResult",
    "RerankerService",
    "Tier1MemoryCache",
    "Tier2ResponseCache",
    "OpenRouterClient",
    "HealthChecker",
    "MetricsCollector",
    "VersionManager",
    "VersionInfo",
    "VersionNotFoundError",
    "make_storage_key",
    "ObjectStorage",
    "ObjectStorageError",
    "MemoryObjectStorage",
    "FilesystemObjectStorage",
    "S3ObjectStorage",
    "WebsiteChunkPayload",
    "WebsiteDocument",
    "WebsiteProjectAdapter",
    "WebsiteProjectConfig",
]
