"""Compatibility shim for project scope and filter schemas."""

from project_service.schemas.scope import ProjectQueryScope, ProjectRetrievalFilter

BaseQueryScope = ProjectQueryScope
BaseRetrievalFilter = ProjectRetrievalFilter

__all__ = [
    "BaseQueryScope",
    "BaseRetrievalFilter",
    "ProjectQueryScope",
    "ProjectRetrievalFilter",
]
