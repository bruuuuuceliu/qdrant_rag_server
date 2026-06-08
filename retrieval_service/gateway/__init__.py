"""Gateway package — request validation, concurrency control, and execution plans.

Layered by concern:

- ``gateway.errors`` — exception hierarchy
- ``gateway.requests`` — SearchRequest, IngestRequest input schemas
- ``gateway.plans`` — SearchPlan, IngestPlan assembled DTOs
- ``gateway.limiter`` — AsyncConcurrencyLimiter
- ``gateway.gateway`` — RagGateway orchestrator
- ``gateway.helpers`` — validation/normalization utilities
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
