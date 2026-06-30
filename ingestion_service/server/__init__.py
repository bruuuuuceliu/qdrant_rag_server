"""Ingestion service server package."""

__all__ = [
    "IngestionHelperHandler",
    "IngestionHelperServerContext",
    "BrokerIngestionApp",
    "create_helper_app",
]


def __getattr__(name: str):
    if name == "IngestionHelperHandler":
        from ingestion_service.server import domain_handler

        return getattr(domain_handler, name)
    if name in {"IngestionHelperServerContext", "create_helper_app"}:
        from ingestion_service.server import helper_app

        return getattr(helper_app, name)
    if name == "BrokerIngestionApp":
        from ingestion_service.server import broker_runtime

        return getattr(broker_runtime, name)
    raise AttributeError(name)
