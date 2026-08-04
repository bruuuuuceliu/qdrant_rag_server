"""Token-bucket rate limiting shared by service edges.

The bucket is time-based on ``time.monotonic`` and is safe to use from a single
event-loop thread (there is no ``await`` inside ``try_acquire``, so the
check-and-consume is atomic within one loop iteration). For multi-threaded
producers, wrap the instance with a lock.
"""

from __future__ import annotations

import time


class TokenBucket:
    """Fixed-capacity token bucket: ``rate`` tokens refill per second."""

    def __init__(self, rate: float, capacity: int) -> None:
        if rate < 0:
            raise ValueError("rate must be non-negative")
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.rate = rate
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._updated = time.monotonic()

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Consume ``tokens`` and return True when available."""
        if tokens <= 0:
            return True
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._updated = now
        if self._tokens < tokens:
            return False
        self._tokens -= tokens
        return True

    def reset(self) -> None:
        """Refill the bucket to capacity."""
        self._tokens = self.capacity
        self._updated = time.monotonic()

    @property
    def available(self) -> float:
        """Current token count (best-effort, may lag one tick)."""
        return self._tokens
