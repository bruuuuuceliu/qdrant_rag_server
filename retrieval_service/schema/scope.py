"""Compatibility shim for query scope schemas."""

from project_service.schemas import (
    ProjectQueryScope as BaseQueryScope,
    ProjectRetrievalFilter as BaseRetrievalFilter,
)

__all__ = ["BaseQueryScope", "BaseRetrievalFilter"]
