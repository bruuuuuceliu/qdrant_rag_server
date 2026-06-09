"""Compatibility shim for project gateway errors."""

from project_service.gateway.errors import (
    ConcurrencyLimitExceededError,
    GatewayError,
    InvalidRequestError,
    ProjectScopeMismatchError,
)

__all__ = [
    "ConcurrencyLimitExceededError",
    "GatewayError",
    "InvalidRequestError",
    "ProjectScopeMismatchError",
]
