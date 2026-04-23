"""
Finnhub — insider trades + analyst recommendations.
https://finnhub.io/docs/api

Free tier: 60 calls/min. Endpoints used (v0.6 surface):
- /stock/insider-transactions : insider buy/sell aggregate
- /stock/recommendation       : analyst buy/hold/sell history

All methods are defensive — on any error, return empty structure. Stage
keeps producing a verdict; Finnhub is color, not signal.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import requests

from engine.cache import cache_get, cache_set
from shared.config import ApiKeys, Config

API_BASE = "https://finnhub.io/api/v1"


class FinnhubError(RuntimeError):
    pass


def _take_token() -> None:
    try:
        from shared.ratelimit import require_token

        require_token("finnhub")
    except ImportError:
        pass
    except Exception as e:
        raise FinnhubError(f"rate-limit: {e}")


def _api_get(keys: ApiKeys, path: str, params: dict) -> dict | list:
    if not keys.finnhub:
        raise FinnhubError("FINNHUB_API_KEY missing")
    _take_token()
    params = dict(params)
    params["token"] = keys.finnhub
    try:
        r = requests.get(f"{API_BASE}/{path}", params=params, timeout=15)
    except Exception as e:
        raise FinnhubError(f"network error: {e}")
    if r.status_code == 401:
        raise FinnhubError("Invalid FINNHUB_API_KEY (401)")
    if r.status_code == 429:
        raise FinnhubError("Finnhub rate-limited (429)")
    if r.status_code != 200:
        raise FinnhubError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _cached_api_get(
    cfg: Config,
    keys: ApiKeys,
    path: str,
    params: dict,
    cache_ns: str,
    ttl: int = 21600,
) -> dict | list:
    key = f"{path}?{'&'.join(f'{k}={v}' for k, v in sorted(params.items()))}"
    cached = cache_get(cfg, cache_ns, key, ttl)
    if cached is not None:
        return cached.get("value") if isinstance(cached, dict) and "value" in cached else cached
    data = _api_get(keys, path, params)
    cache_set(cfg, cache_ns, key, {"value": data})
    return data


def fetch_insider_transactions(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    days: int = 180,
) -> dict:
    """Summary: last N days of insider txns, net share delta, dollar volume.

    Returns {"net_shares": int, "net_dollars": float, "tx_count": int, "rows": [...]}.
    """
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    data = _cached_api_get(
        cfg,
        keys,
        "stock/insider-transactions",
        {"symbol": ticker, "from": since},
        "fh_insider",
        ttl=21600,
    )
    rows = data.get("data", []) if isinstance(data, dict) else []
    net_shares = 0
    net_dollars = 0.0
    for r in rows:
        change = r.get("change") or 0
        price = r.get("transactionPrice") or 0
        net_shares += change
        net_dollars += change * price
    return {
        "net_shares": net_shares,
        "net_dollars": round(net_dollars, 2),
        "tx_count": len(rows),
        "rows": rows[:10],  # keep top-10 for snapshot
        "window_days": days,
    }


def fetch_recommendation_trends(cfg: Config, keys: ApiKeys, ticker: str) -> list[dict]:
    """Analyst recommendation history, newest first.

    Each row: {"period": "2026-04-01", "strongBuy": N, "buy": N, "hold": N,
               "sell": N, "strongSell": N}.
    """
    data = _cached_api_get(
        cfg,
        keys,
        "stock/recommendation",
        {"symbol": ticker},
        "fh_reco",
        ttl=21600,
    )
    if isinstance(data, list):
        return data[:6]
    return []


def summarize_consensus(rows: list[dict]) -> dict:
    """Reduce recommendation_trends to the latest row + a directional label."""
    if not rows:
        return {"label": "n/a", "total_analysts": 0}
    latest = rows[0]
    sb = latest.get("strongBuy", 0) or 0
    b = latest.get("buy", 0) or 0
    h = latest.get("hold", 0) or 0
    s = latest.get("sell", 0) or 0
    ss = latest.get("strongSell", 0) or 0
    total = sb + b + h + s + ss
    if total == 0:
        return {"label": "n/a", "total_analysts": 0}
    bull = (sb + b) / total
    bear = (s + ss) / total
    if bull > 0.7:
        label = "overwhelmingly_bullish"
    elif bull > 0.5:
        label = "bullish"
    elif bear > 0.3:
        label = "skeptical"
    else:
        label = "mixed"
    return {
        "label": label,
        "period": latest.get("period", ""),
        "total_analysts": total,
        "bullish_pct": round(bull * 100, 1),
        "bearish_pct": round(bear * 100, 1),
        "breakdown": {"strong_buy": sb, "buy": b, "hold": h, "sell": s, "strong_sell": ss},
    }


# --- Health check ---


def test_connection(keys: ApiKeys) -> tuple[bool, str]:
    try:
        data = _api_get(keys, "stock/recommendation", {"symbol": "AAPL"})
        if isinstance(data, list) and data:
            return True, f"connected; {len(data)} AAPL recommendation periods"
        return False, "empty response"
    except FinnhubError as e:
        return False, str(e)
