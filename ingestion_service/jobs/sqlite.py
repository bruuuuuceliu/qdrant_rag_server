"""Placeholder for durable SQLite ingestion job storage."""

from ingestion_service.jobs.repository import MemoryIngestionJobRepository


class SQLiteIngestionJobRepository(MemoryIngestionJobRepository):
    """Compatibility placeholder until durable storage is implemented."""
