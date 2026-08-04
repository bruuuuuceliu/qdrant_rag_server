"""Operational foundation shared by all services.

Generic, transport-neutral building blocks only — no service business logic:
- ``metrics``    Prometheus metric singletons and ``/metrics`` rendering.
- ``server``     minimal HTTP ``/healthz`` + ``/readyz`` + ``/metrics`` server.
- ``shutdown``   signal-driven graceful shutdown helper for worker entrypoints.

Structured logging and correlation-ID threading live in ``shared.logging``.
"""
