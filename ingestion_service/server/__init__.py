"""Ingestion service server package."""

__all__ = ["IngestionAppContext", "create_app"]


def __getattr__(name: str):
    if name in __all__:
        from ingestion_service.server import app

        return getattr(app, name)
    raise AttributeError(name)
