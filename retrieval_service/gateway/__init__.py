"""Compatibility shim for the project gateway.

Canonical project gateway code lives in ``project_service.gateway``.
"""

from project_service.gateway import (
    AsyncConcurrencyLimiter,
    ConcurrencyLimitExceededError,
    GatewayError,
    IngestPlan,
    IngestRequest,
    InvalidRequestError,
    ProjectScopeMismatchError,
    RagGateway,
    SearchPlan,
    SearchRequest,
)

__all__ = [
    "AsyncConcurrencyLimiter",
    "ConcurrencyLimitExceededError",
    "GatewayError",
    "IngestPlan",
    "IngestRequest",
    "InvalidRequestError",
    "ProjectScopeMismatchError",
    "RagGateway",
    "SearchPlan",
    "SearchRequest",
]
