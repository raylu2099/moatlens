"""
MarketAux — news aggregation with entity-level sentiment scoring.
https://www.marketaux.com/documentation

Free tier: 100 requests/day. Endpoints used:
- /v1/news/all : news articles with per-entity sentiment_score [-1, +1]

Defensive: on any error, return empty structure so stage keeps producing
a verdict. MarketAux is color, not signal.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import requests

from engine.cache import cache_get, cache_set
from shared.config import ApiKeys, Config

API_BASE = "https://api.marketaux.com/v1"


class MarketauxError(RuntimeError):
    pass


def _take_token() -> None:
    try:
        from shared.ratelimit import require_token

        require_token("marketaux")
    except ImportError:
        pass
    except Exception as e:
        raise MarketauxError(f"rate-limit: {e}")


def _api_get(keys: ApiKeys, path: str, params: dict) -> dict:
    if not keys.marketaux:
        raise MarketauxError("MARKETAUX_API_KEY missing")
    _take_token()
    params = dict(params)
    params["api_token"] = keys.marketaux
    try:
        r = requests.get(f"{API_BASE}/{path}", params=params, timeout=15)
    except Exception as e:
        raise MarketauxError(f"network error: {e}")
    if r.status_code == 401:
        raise MarketauxError("Invalid MARKETAUX_API_KEY (401)")
    if r.status_code == 402:
        raise MarketauxError("MarketAux daily quota exhausted (402)")
    if r.status_code == 429:
        raise MarketauxError("MarketAux rate-limited (429)")
    if r.status_code != 200:
        raise MarketauxError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def fetch_news_sentiment(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    days: int = 30,
    limit: int = 20,
) -> dict:
    """Aggregate last N days of news sentiment for ticker.

    Returns {
        "avg_sentiment": float in [-1, +1],
        "article_count": int,
        "positive_pct": float,
        "negative_pct": float,
        "top_headlines": [{"title", "sentiment_score", "published_at"}],
    }. Uses 6h cache (news changes fast but not intraday for audits).
    """
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    cache_key = f"{ticker}:{days}:{limit}"
    cached = cache_get(cfg, "mx_news", cache_key, ttl_seconds=21600)
    if cached is not None:
        return cached.get("value", {})

    data = _api_get(
        keys,
        "news/all",
        {
            "symbols": ticker,
            "language": "en",
            "filter_entities": "true",
            "published_after": since,
            "limit": limit,
        },
    )
    articles = data.get("data", [])
    if not articles:
        result = {
            "avg_sentiment": 0.0,
            "article_count": 0,
            "positive_pct": 0.0,
            "negative_pct": 0.0,
            "top_headlines": [],
            "window_days": days,
        }
        cache_set(cfg, "mx_news", cache_key, {"value": result})
        return result

    scores = []
    positive = 0
    negative = 0
    headlines = []
    for a in articles:
        entities = a.get("entities", [])
        # Only count entity scores for our ticker
        for e in entities:
            if e.get("symbol", "").upper() == ticker.upper():
                s = e.get("sentiment_score")
                if s is not None:
                    scores.append(s)
                    if s > 0.1:
                        positive += 1
                    elif s < -0.1:
                        negative += 1
                    headlines.append(
                        {
                            "title": a.get("title", "")[:200],
                            "sentiment_score": s,
                            "published_at": a.get("published_at", ""),
                            "url": a.get("url", ""),
                        }
                    )
                break

    total = len(scores)
    avg = sum(scores) / total if total else 0.0
    result = {
        "avg_sentiment": round(avg, 3),
        "article_count": total,
        "positive_pct": round(100 * positive / total, 1) if total else 0.0,
        "negative_pct": round(100 * negative / total, 1) if total else 0.0,
        "top_headlines": sorted(
            headlines,
            key=lambda h: abs(h.get("sentiment_score") or 0),
            reverse=True,
        )[:5],
        "window_days": days,
    }
    cache_set(cfg, "mx_news", cache_key, {"value": result})
    return result


def sentiment_label(avg: float, article_count: int) -> str:
    """Human label for a sentiment aggregate. 'n/a' if too few articles."""
    if article_count < 3:
        return "n/a"
    if avg > 0.25:
        return "strongly_positive"
    if avg > 0.05:
        return "mildly_positive"
    if avg < -0.25:
        return "strongly_negative"
    if avg < -0.05:
        return "mildly_negative"
    return "neutral"


# --- Health check ---


def test_connection(keys: ApiKeys) -> tuple[bool, str]:
    try:
        data = _api_get(
            keys,
            "news/all",
            {
                "symbols": "AAPL",
                "language": "en",
                "limit": 1,
            },
        )
        n = len(data.get("data", []))
        return True, f"connected; {n} AAPL article in last 24h"
    except MarketauxError as e:
        return False, str(e)
