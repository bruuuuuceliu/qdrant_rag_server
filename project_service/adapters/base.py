"""Project adapter contracts and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from retrieval_service.ingest.ingester import AdapterBackedIngester, Ingester
from project_service.schemas import (
    ProjectChunk,
    ProjectChunkPayload,
    ProjectConfig,
    ProjectDocument,
    ProjectQueryScope,
    ProjectRetrievalFilter,
)


class AdapterNotFoundError(LookupError):
    """Raised when no adapter is registered for a project type."""


class DuplicateAdapterError(ValueError):
    """Raised when registering the same project type twice."""


class ProjectAdapter(ABC):
    """Base interface implemented by every project-specific adapter."""

    project_type: str

    @abstractmethod
    async def get_config(self, project_id: str) -> ProjectConfig:
        """Load the project config for a project."""

    @abstractmethod
    async def build_query_scope(self, request: Any) -> ProjectQueryScope:
        """Build the enforced query scope from an incoming request."""

    @abstractmethod
    async def build_retrieval_filter(
        self, scope: ProjectQueryScope
    ) -> ProjectRetrievalFilter:
        """Build the retrieval filter used by Qdrant search."""

    async def select_ingester(
        self,
        request: Any,
        *,
        config: ProjectConfig | None = None,
    ) -> Ingester:
        """Select the ingester implementation for one ingest request."""
        del request, config
        return AdapterBackedIngester(self)

    async def parse_document(self, input_data: Any) -> ProjectDocument:
        """Legacy hook for adapters that still own document parsing."""
        raise NotImplementedError

    async def build_chunks(self, document: ProjectDocument) -> Sequence[ProjectChunk]:
        """Legacy hook for adapters that still own chunking."""
        raise NotImplementedError

    async def build_payload(self, chunk: ProjectChunk) -> ProjectChunkPayload:
        """Legacy hook for adapters that still own payload rendering."""
        raise NotImplementedError

    @abstractmethod
    async def build_prompt(
        self,
        query: str,
        chunks: Sequence[ProjectChunkPayload],
        scope: ProjectQueryScope,
    ) -> str:
        """Build the generation prompt for a query and retrieved chunks."""


class ProjectAdapterRegistry:
    """Maps project types to adapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProjectAdapter] = {}

    def register(self, adapter: ProjectAdapter) -> None:
        project_type = _normalize_project_type(adapter.project_type)
        if project_type in self._adapters:
            raise DuplicateAdapterError(
                f"adapter already registered for project_type={project_type!r}"
            )
        self._adapters[project_type] = adapter

    def register_many(self, adapters: Iterable[ProjectAdapter]) -> None:
        for adapter in adapters:
            self.register(adapter)

    def get(self, project_type: str) -> ProjectAdapter:
        normalized = _normalize_project_type(project_type)
        try:
            return self._adapters[normalized]
        except KeyError as exc:
            raise AdapterNotFoundError(
                f"no adapter registered for project_type={normalized!r}"
            ) from exc

    def has(self, project_type: str) -> bool:
        return _normalize_project_type(project_type) in self._adapters

    def project_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


class ProjectTypeRepository(Protocol):
    """Repository surface needed to resolve adapters by project ID."""

    async def get_project_type(self, project_id: str) -> str:
        """Return the configured project type for a project."""


class ProjectAdapterResolver:
    """Resolves project IDs to project adapters through config and registry."""

    def __init__(
        self,
        *,
        project_types: ProjectTypeRepository,
        registry: ProjectAdapterRegistry,
    ) -> None:
        self._project_types = project_types
        self._registry = registry

    async def resolve(self, project_id: str) -> ProjectAdapter:
        project_type = await self._project_types.get_project_type(project_id)
        return self._registry.get(project_type)


def _normalize_project_type(project_type: str) -> str:
    if not project_type or not project_type.strip():
        raise ValueError("project_type is required")
    return project_type.strip().lower()
