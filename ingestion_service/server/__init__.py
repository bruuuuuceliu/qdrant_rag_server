"""Ingestion service server package."""

__all__ = [
    "IngestionApiError",
    "IngestionApiHandler",
    "IngestionApiServerContext",
    "IngestionAppContext",
    "IngestionResponseEnvelope",
    "IngestionStatusCommand",
    "create_api_app",
    "create_app",
    "job_to_mapping",
]


def __getattr__(name: str):
    if name in {"IngestionAppContext", "create_app"}:
        from ingestion_service.server import app

        return getattr(app, name)
    if name in {"IngestionApiServerContext", "create_api_app"}:
        from ingestion_service.server import api

        return getattr(api, name)
    if name == "IngestionApiHandler":
        from ingestion_service.server import handler

        return getattr(handler, name)
    if name in {
        "IngestionApiError",
        "IngestionResponseEnvelope",
        "IngestionStatusCommand",
        "job_to_mapping",
    }:
        from ingestion_service.server import contracts

        return getattr(contracts, name)
    raise AttributeError(name)
