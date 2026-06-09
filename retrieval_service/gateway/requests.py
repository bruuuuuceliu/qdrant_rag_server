"""Compatibility shim for project gateway request schemas."""

from project_service.gateway.requests import IngestRequest, SearchRequest

__all__ = ["IngestRequest", "SearchRequest"]
