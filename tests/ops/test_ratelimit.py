"""Token-bucket rate limiter tests."""

from __future__ import annotations

import time

import pytest

from shared.ops.ratelimit import TokenBucket


def test_bucket_starts_full() -> None:
    bucket = TokenBucket(rate=1.0, capacity=5)
    assert bucket.available == 5
    assert bucket.try_acquire()
    assert bucket.available == 4


def test_bucket_exhausts_without_refill() -> None:
    bucket = TokenBucket(rate=0.0, capacity=2)
    assert bucket.try_acquire()
    assert bucket.try_acquire()
    assert not bucket.try_acquire()


def test_bucket_refills_over_time() -> None:
    bucket = TokenBucket(rate=10.0, capacity=1)
    assert bucket.try_acquire()
    assert not bucket.try_acquire()
    time.sleep(0.15)
    assert bucket.try_acquire()


def test_bucket_caps_at_capacity() -> None:
    bucket = TokenBucket(rate=1000.0, capacity=3)
    time.sleep(0.05)
    # Long idle time does not grow tokens beyond capacity.
    assert bucket.available <= 3
    assert bucket.available > 3 - 1e-6


def test_reset_refills() -> None:
    bucket = TokenBucket(rate=0.0, capacity=4)
    for _ in range(4):
        assert bucket.try_acquire()
    assert not bucket.try_acquire()
    bucket.reset()
    assert bucket.try_acquire()


def test_invalid_arguments_rejected() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=-1, capacity=1)
    with pytest.raises(ValueError):
        TokenBucket(rate=1, capacity=0)
