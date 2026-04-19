"""Rate limiter — token-bucket correctness."""
from __future__ import annotations

import pytest

from shared.ratelimit import (
    RateLimitExceeded, TokenBucket, require_token, reset_all,
)


def test_token_bucket_starts_full():
    b = TokenBucket(rate_per_min=60, burst=5)
    # Should allow 5 takes immediately
    for _ in range(5):
        assert b.take() is True


def test_token_bucket_exhausts_after_burst():
    b = TokenBucket(rate_per_min=6, burst=3)   # slow refill
    for _ in range(3):
        assert b.take() is True
    # 4th call fails — tokens not refilled yet
    assert b.take() is False


def test_token_bucket_refills_over_time(monkeypatch):
    import time as _t
    fake_clock = [0.0]
    monkeypatch.setattr(
        "shared.ratelimit.time",
        type("m", (), {"monotonic": staticmethod(lambda: fake_clock[0])})
    )
    b = TokenBucket(rate_per_min=60, burst=1)   # 1 token/sec, burst 1
    assert b.take() is True
    assert b.take() is False
    # Advance clock by 1 second → ~1 token back
    fake_clock[0] = 1.0
    assert b.take() is True


def test_require_token_raises_when_depleted(monkeypatch):
    """With very restrictive bucket, require_token should raise."""
    from shared import ratelimit as rl
    reset_all()
    # Replace claude bucket with a tiny one
    rl._BUCKETS["claude"] = TokenBucket(rate_per_min=1, burst=1)
    require_token("claude")    # first call OK
    with pytest.raises(RateLimitExceeded):
        require_token("claude")   # second immediately fails
    reset_all()


def test_unknown_provider_no_op():
    """Unknown providers don't raise and don't rate-limit."""
    require_token("made_up_provider")
    require_token("made_up_provider")
    require_token("made_up_provider")
