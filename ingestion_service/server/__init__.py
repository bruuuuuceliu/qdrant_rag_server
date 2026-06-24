"""Ingestion service server package."""

__all__ = [
    "IngestionApiError",
    "IngestionApiHandler",
    "IngestionHelperHandler",
    "IngestionHelperServerContext",
    "IngestionApiServerContext",
    "IngestionAppContext",
    "BrokerIngestionApp",
    "IngestionResponseEnvelope",
    "IngestionStatusCommand",
    "create_api_app",
    "create_app",
    "create_helper_app",
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
    if name == "IngestionHelperHandler":
        from ingestion_service.server import domain_handler

        return getattr(domain_handler, name)
    if name in {"IngestionHelperServerContext", "create_helper_app"}:
        from ingestion_service.server import helper_app

        return getattr(helper_app, name)
    if name == "BrokerIngestionApp":
        from ingestion_service.server import broker_runtime

        return getattr(broker_runtime, name)
    if name in {
        "IngestionApiError",
        "IngestionResponseEnvelope",
        "IngestionStatusCommand",
        "job_to_mapping",
    }:
        from ingestion_service.server import contracts

        return getattr(contracts, name)
    raise AttributeError(name)
