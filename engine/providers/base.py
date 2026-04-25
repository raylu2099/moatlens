"""
Shared HTTP + cache plumbing for provider modules (v0.6.1 audit fix P0-4/P1-7).

Four v0.6 providers (sec_api, finnhub, marketaux, fda) grew independently and
ended up copying the same four patterns 3-5 times each:
- rate-limit gate (`_take_token`)
- `requests.get/post` + network-error wrap
- cache envelope ({"value": …}) + hit/miss handling
- status-code triage (401 / 429 / other)

Design choice: **module-level helpers**, not a class hierarchy. Each provider
keeps its existing module API (`finnhub.fetch_recommendation_trends(...)`,
`sec_api.fetch_mda(...)`, etc.) — so callers in `engine/stages/_enrichments.py`,
`bin/doctor.py`, and tests don't change.

Helpers also enforce two discipline invariants across all providers:
- `verify=True` is explicit on every requests call (P2-6)
- API keys travel in headers (Authorization / X-Finnhub-Token etc.) whenever
  the provider supports it — not in query strings where they'd end up in
  proxy logs / browser history (P0-4). Providers whose API requires a query
  param key (e.g. marketaux) document that explicitly at the callsite.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import requests

from engine.cache import cache_get, cache_set

# Default timeouts — each provider can override at call site.
DEFAULT_TIMEOUT = 20
DEFAULT_TIMEOUT_SLOW = 30  # for SEC extractor and similar bulk-text endpoints

# Lazy logger — lets us time every HTTP call without importing the
# full logging_setup config tree from here.
_log = logging.getLogger("moatlens.providers.http")


def rate_limit_gate(provider_name: str, error_class: type[Exception]) -> None:
    """Take one token from shared.ratelimit for `provider_name`.

    Silent on ImportError (ratelimit is technically optional — dev environments
    may run without it). Wraps any other exception in `error_class` so the
    provider's public API stays consistent.
    """
    try:
        from shared.ratelimit import require_token
    except ImportError:
        return
    try:
        require_token(provider_name)
    except Exception as e:
        raise error_class(f"rate-limit: {e}")


def http_get(
    url: str,
    error_class: type[Exception],
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> requests.Response:
    """GET with explicit `verify=True`, timeout, and uniform network-error wrap.

    Returns the raw Response so the caller can inspect `status_code` and
    parse per-provider error bodies. Network-layer exceptions (DNS, TLS,
    connection reset, timeout) are caught and re-raised as `error_class`.

    Logs `elapsed_ms` + response status at DEBUG so a "why was yesterday
    slow?" investigation can answer without re-running the audit.
    """
    t0 = time.monotonic()
    try:
        r = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            verify=True,
        )
    except requests.exceptions.RequestException as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _log.info(
            "http_get network-error",
            extra={"url": url, "elapsed_ms": elapsed_ms, "err": str(e)[:120]},
        )
        raise error_class(f"network error: {e}")
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    _log.debug(
        "http_get",
        extra={"url": url, "status": r.status_code, "elapsed_ms": elapsed_ms},
    )
    return r


def http_post(
    url: str,
    error_class: type[Exception],
    *,
    params: dict | None = None,
    headers: dict | None = None,
    json: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> requests.Response:
    """POST with explicit `verify=True`. See `http_get` for the rationale.
    Also logs elapsed_ms at DEBUG / INFO-on-error (same contract)."""
    t0 = time.monotonic()
    try:
        r = requests.post(
            url,
            params=params,
            headers=headers,
            json=json,
            timeout=timeout,
            verify=True,
        )
    except requests.exceptions.RequestException as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _log.info(
            "http_post network-error",
            extra={"url": url, "elapsed_ms": elapsed_ms, "err": str(e)[:120]},
        )
        raise error_class(f"network error: {e}")
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    _log.debug(
        "http_post",
        extra={"url": url, "status": r.status_code, "elapsed_ms": elapsed_ms},
    )
    return r


def cached_call(
    cfg,
    cache_ns: str,
    cache_key: str,
    ttl: int,
    fetcher: Callable[[], Any],
) -> Any:
    """Generic cache wrapper: hit returns stored value, miss runs `fetcher()`
    and persists the return.

    Cache envelope is handled by shared `cache_get` / `cache_set` — this helper
    just provides the "call-through on miss" glue. Providers pass whatever
    dict they want cached; they get it back unchanged on hit.
    """
    cached = cache_get(cfg, cache_ns, cache_key, ttl)
    if cached is not None:
        return cached
    value = fetcher()
    cache_set(cfg, cache_ns, cache_key, value)
    return value


def stable_cache_key(*parts: Any) -> str:
    """Join arbitrary parts into a deterministic cache key (stable across
    Python runs). `params` dicts are sorted so `{a:1,b:2}` and `{b:2,a:1}`
    share the same key — prevents cache fragmentation."""
    out = []
    for p in parts:
        if isinstance(p, dict):
            out.append("&".join(f"{k}={p[k]}" for k in sorted(p)))
        else:
            out.append(str(p))
    return "|".join(out)
