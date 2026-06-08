"""Gateway error classes."""

from __future__ import annotations


class GatewayError(Exception):
    """Base class for structured gateway errors."""

    code = "gateway_error"


class InvalidRequestError(GatewayError):
    """Raised when a request fails gateway validation."""

    code = "invalid_request"


class ProjectScopeMismatchError(GatewayError):
    """Raised when an adapter tries to change the enforced request scope."""

    code = "project_scope_mismatch"


class ConcurrencyLimitExceededError(GatewayError):
    """Raised when per-project or per-user concurrency limits are saturated."""

    code = "concurrency_limit_exceeded"
