"""Ingestion service server bootstrap."""

from ingestion_service.server.app import IngestionAppContext, create_app

__all__ = ["IngestionAppContext", "create_app"]
