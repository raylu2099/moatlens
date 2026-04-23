"""
Token-bucket rate limiter for provider calls.

Prevents a runaway loop from punching through API quotas. Each provider gets
its own bucket with configurable rate + burst size. Non-blocking — if bucket
is empty, raises RateLimitExceeded.

Thread-safe via simple lock. Not async-aware (our providers are sync).

Bucket policy (per call, per process — not across restarts):
- claude:           20/min, burst 10
- perplexity:       20/min, burst 10
- financial_datasets: 60/min, burst 20
- fred:             30/min, burst 15
- sec_api_io:       30/min, burst 10
- finnhub:          60/min, burst 20     (free tier: 60/min)
- marketaux:        10/min, burst 5      (free tier: 100/day → conservative)
- fda:              30/min, burst 15     (openFDA + ClinicalTrials.gov, no key)

These are *very* loose for a single user — they exist solely to catch bugs
(accidental while True), not to enforce provider quotas.
"""

from __future__ import annotations

import threading
import time


class RateLimitExceeded(RuntimeError):
    pass


class TokenBucket:
    def __init__(self, rate_per_min: float, burst: int):
        self.rate_per_sec = rate_per_min / 60.0
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.last = time.monotonic()
        self._lock = threading.Lock()

    def take(self, n: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_sec)
            self.last = now
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False


_BUCKETS: dict[str, TokenBucket] = {
    "claude": TokenBucket(20, 10),
    "perplexity": TokenBucket(20, 10),
    "financial_datasets": TokenBucket(60, 20),
    "fred": TokenBucket(30, 15),
    "sec_api_io": TokenBucket(30, 10),
    "finnhub": TokenBucket(60, 20),
    "marketaux": TokenBucket(10, 5),
    "fda": TokenBucket(30, 15),
}


def require_token(provider: str) -> None:
    """Take a token for `provider`, or raise RateLimitExceeded."""
    bucket = _BUCKETS.get(provider)
    if bucket is None:
        return  # unknown provider, no limit
    if not bucket.take(1):
        raise RateLimitExceeded(f"{provider}: rate limit exceeded. Sanity-check for runaway loops.")


def reset_all() -> None:
    """Reset all buckets to full. Used in tests."""
    for bucket in _BUCKETS.values():
        bucket.tokens = bucket.capacity
        bucket.last = time.monotonic()
