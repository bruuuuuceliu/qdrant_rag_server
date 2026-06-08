"""Legacy re-export shim — gateway types have been split into focused modules.

Prefer importing from the gateway package or from the individual modules:

    from retrieval_service.gateway import RagGateway, SearchRequest
    from retrieval_service.gateway.errors import InvalidRequestError
    from retrieval_service.gateway.limiter import AsyncConcurrencyLimiter
"""

from retrieval_service.gateway.errors import (
    ConcurrencyLimitExceededError,
    GatewayError,
    InvalidRequestError,
    ProjectScopeMismatchError,
)
from retrieval_service.gateway.requests import IngestRequest, SearchRequest
from retrieval_service.gateway.plans import IngestPlan, SearchPlan
from retrieval_service.gateway.limiter import AsyncConcurrencyLimiter
from retrieval_service.gateway.gateway import RagGateway

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
