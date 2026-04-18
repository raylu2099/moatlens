"""
FRED (Federal Reserve Economic Data) — macro provider.

Used for:
- Current 10Y Treasury yield (DCF discount rate / WACC)
- Credit spreads (BAA OAS)
- Historical real rates (TIPS)

Gracefully no-ops if FRED_API_KEY missing (returns None). FRED is optional
— the engine can fall back to hardcoded WACC if user doesn't have a key.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import requests

from engine.cache import cache_get, cache_set
from shared.config import ApiKeys, Config


FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def fetch_latest_value(cfg: Config, keys: ApiKeys, series_id: str) -> float | None:
    if not keys.fred:
        return None

    cache_key = f"{series_id}_latest"
    cached = cache_get(cfg, "fred", cache_key, cfg.cache_macro_ttl)
    if cached is not None:
        return cached.get("value")

    start = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    end = date.today().strftime("%Y-%m-%d")
    try:
        r = requests.get(
            FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": keys.fred,
                "file_type": "json",
                "observation_start": start,
                "observation_end": end,
                "sort_order": "desc",
                "limit": 30,
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None
        obs = r.json().get("observations", [])
        for o in obs:
            v = o.get("value")
            if v and v != ".":
                try:
                    val = float(v)
                    cache_set(cfg, "fred", cache_key, {"value": val, "date": o.get("date")})
                    return val
                except ValueError:
                    continue
        return None
    except Exception as e:
        print(f"[fred] {series_id}: {e}", file=sys.stderr)
        return None


def fetch_risk_free_rate(cfg: Config, keys: ApiKeys) -> float:
    """10Y Treasury — default WACC base. Falls back to 4.3% if unavailable."""
    val = fetch_latest_value(cfg, keys, "DGS10")
    if val is not None:
        return val
    return 4.3


def fetch_credit_spread(cfg: Config, keys: ApiKeys) -> float | None:
    """BAA corporate bond OAS — signals credit stress."""
    return fetch_latest_value(cfg, keys, "BAA10Y")


def test_connection(keys: ApiKeys) -> tuple[bool, str]:
    if not keys.fred:
        return False, "FRED_API_KEY not set (optional — will use fallback rates)"
    try:
        url = f"{FRED_BASE}?series_id=DGS10&api_key={keys.fred}&file_type=json&limit=1&sort_order=desc"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            obs = r.json().get("observations", [])
            if obs:
                return True, f"connected; 10Y = {obs[0].get('value')}%"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)
