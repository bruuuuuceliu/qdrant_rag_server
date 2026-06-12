"""Ingestion service configuration namespace."""

from configs.ingestion.config import IngestionSettings, load_ingestion_settings

__all__ = ["IngestionSettings", "load_ingestion_settings"]
