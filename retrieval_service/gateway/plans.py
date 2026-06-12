"""Compatibility shim for project gateway execution plans."""

from project_service.gateway.plans import IngestPlan, SearchPlan

__all__ = ["IngestPlan", "SearchPlan"]
