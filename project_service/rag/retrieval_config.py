"""Compatibility shim for reusable retrieval configuration."""

from retrieval_service.retrieval.config import (
    FusionMethod,
    NerProvider,
    ProjectBM25Settings,
    ProjectNerSettings,
    ProjectRetrievalSettings,
    RetrievalMode,
    parse_retrieval_settings,
)

__all__ = [
    "FusionMethod",
    "NerProvider",
    "ProjectBM25Settings",
    "ProjectNerSettings",
    "ProjectRetrievalSettings",
    "RetrievalMode",
    "parse_retrieval_settings",
]
