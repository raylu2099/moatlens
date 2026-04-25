"""
Shared data cache — avoids hitting providers multiple times for the same
ticker within a TTL window.

Critical for BYOK performance: when 10 users audit NVDA on the same day,
Financial Datasets should be called once, not 10 times. This also protects
the user's own API quota.

Public market data (financials, prices, macro) → shared cache.
Claude analyses and Perplexity searches → NOT cached (user-specific).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from shared.config import Config


def _key_to_path(cache_dir: Path, namespace: str, key: str) -> Path:
    """Hash the key to a safe filename."""
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    d = cache_dir / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


def cache_get(cfg: Config, namespace: str, key: str, ttl_seconds: int) -> dict | None:
    """Return cached value if fresh, else None."""
    path = _key_to_path(cfg.cache_dir, namespace, key)
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - entry.get("stored_at", 0) > ttl_seconds:
            return None
        return entry.get("value")
    except Exception:
        return None


def cache_set(cfg: Config, namespace: str, key: str, value: dict) -> None:
    """Store value with current timestamp."""
    path = _key_to_path(cfg.cache_dir, namespace, key)
    entry = {
        "stored_at": time.time(),
        "value": value,
        "key": key,
    }
    path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")


def cache_clear(cfg: Config, namespace: str | None = None) -> int:
    """Clear a namespace or entire cache. Returns files deleted."""
    root = cfg.cache_dir / namespace if namespace else cfg.cache_dir
    if not root.exists():
        return 0
    count = 0
    for p in root.rglob("*.json"):
        p.unlink()
        count += 1
    return count


def cache_clear_stale(cfg: Config, max_age_seconds: int = 30 * 86400) -> int:
    """Delete cache entries whose `stored_at` is older than `max_age_seconds`.

    Called by `bin/nightly.sh` to cap cache disk footprint. The default 30 days
    is deliberately looser than any individual namespace TTL (longest is 24h
    for macro) so this job never surprises the running app by deleting a
    still-fresh entry — it only evicts obviously abandoned ones.

    Namespace TTLs already make stale reads return None, so this job is
    about bounded disk growth, not correctness.
    """
    root = cfg.cache_dir
    if not root.exists():
        return 0
    now = time.time()
    count = 0
    for p in root.rglob("*.json"):
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
            stored = entry.get("stored_at", 0)
            if now - stored > max_age_seconds:
                p.unlink()
                count += 1
        except Exception:
            # Corrupt cache file — just delete it
            try:
                p.unlink()
                count += 1
            except OSError:
                pass
    return count
