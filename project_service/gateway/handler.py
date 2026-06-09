"""Legacy re-export shim — gateway types have been split into focused modules.

Prefer importing from the gateway package or from the individual modules:

    from project_service.gateway import RagGateway, SearchRequest
    from project_service.gateway.errors import InvalidRequestError
    from project_service.gateway.limiter import AsyncConcurrencyLimiter
"""

from project_service.gateway.errors import (
    ConcurrencyLimitExceededError,
    GatewayError,
    InvalidRequestError,
    ProjectScopeMismatchError,
)
from project_service.gateway.requests import IngestRequest, SearchRequest
from project_service.gateway.plans import IngestPlan, SearchPlan
from project_service.gateway.limiter import AsyncConcurrencyLimiter
from project_service.gateway.gateway import RagGateway

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
