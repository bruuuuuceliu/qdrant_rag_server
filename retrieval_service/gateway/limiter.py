"""Compatibility shim for the project gateway concurrency limiter."""

from project_service.gateway.limiter import (
    AsyncConcurrencyLimiter,
    ConcurrencyLimitExceededError,
)

__all__ = ["AsyncConcurrencyLimiter", "ConcurrencyLimitExceededError"]
