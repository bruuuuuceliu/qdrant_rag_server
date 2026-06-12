"""Routing utilities for ingestion."""

from ingestion_service.routing.capabilities import RuntimeCapabilities, module_available
from ingestion_service.routing.router import FileRouter, RoutedHandler, default_handlers

__all__ = [
    "FileRouter",
    "RoutedHandler",
    "RuntimeCapabilities",
    "default_handlers",
    "module_available",
]
