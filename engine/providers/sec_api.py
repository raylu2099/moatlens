"""
sec-api.io — SEC filing text extractor.
https://sec-api.io/docs

Endpoints used (v0.6 surface):
- /extractor           : extract a specific section (e.g. Item 7 MD&A, Item 1A Risk Factors)
- /full-text-search    : keyword hunt across filings (not used yet, reserved)

Return shape is always a dict/str — never raises to stages. Callers pattern:

    try:
        text = sec_api.fetch_risk_factors(cfg, keys, "AAPL")
    except SecApiError:
        text = ""   # stage proceeds without SEC enrichment

Why defensive: SEC enrichment is a *nice-to-have* color layer on top of
verdict logic. If sec-api is down, audit must still produce a verdict.

Auth: v0.6.1 moved the API key from `?token=` query to the `Authorization`
header. sec-api.io's docs accept both; header form keeps the key out of
proxy access logs, browser history, and our own structured request logs.
"""

from __future__ import annotations

from engine.cache import cache_get, cache_set
from engine.providers.base import (
    DEFAULT_TIMEOUT,
    DEFAULT_TIMEOUT_SLOW,
    http_get,
    http_post,
    rate_limit_gate,
)
from shared.config import ApiKeys, Config

API_BASE = "https://api.sec-api.io"
# Cache SEC filing text aggressively — a 10-K doesn't change for a year.
# We use the fundamentals TTL as a reasonable floor (12h) but in practice
# the text is the same until the next filing.
_FILING_TTL = 86400 * 30  # 30 days


class SecApiError(RuntimeError):
    pass


def _auth_header(keys: ApiKeys) -> dict:
    """Per sec-api.io docs, `Authorization: <key>` is accepted without a
    scheme prefix (not 'Bearer'). We keep that raw to match their examples."""
    return {"Authorization": keys.sec_api_io}


def _latest_10k_url(keys: ApiKeys, ticker: str) -> str | None:
    """Find the URL of the most recent 10-K for ticker."""
    if not keys.sec_api_io:
        raise SecApiError("SEC_API_IO_KEY missing")
    rate_limit_gate("sec_api_io", SecApiError)
    r = http_post(
        API_BASE,
        SecApiError,
        headers=_auth_header(keys),
        json={
            "query": f'ticker:{ticker} AND formType:"10-K"',
            "from": "0",
            "size": "1",
            "sort": [{"filedAt": {"order": "desc"}}],
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if r.status_code != 200:
        raise SecApiError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    filings = data.get("filings", [])
    if not filings:
        return None
    return filings[0].get("linkToFilingDetails") or filings[0].get("linkToHtml")


def _extract_section(keys: ApiKeys, filing_url: str, item: str) -> str:
    """Call the Extractor endpoint for a specific 10-K section."""
    if not keys.sec_api_io:
        raise SecApiError("SEC_API_IO_KEY missing")
    rate_limit_gate("sec_api_io", SecApiError)
    r = http_get(
        f"{API_BASE}/extractor",
        SecApiError,
        headers=_auth_header(keys),
        params={
            "url": filing_url,
            "item": item,
            "type": "text",
        },
        timeout=DEFAULT_TIMEOUT_SLOW,
    )
    if r.status_code != 200:
        raise SecApiError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.text


def _cached_section(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    item: str,
    cache_ns: str,
) -> str:
    key = f"{ticker}:{item}"
    cached = cache_get(cfg, cache_ns, key, ttl_seconds=_FILING_TTL)
    if cached is not None:
        return cached.get("text", "")
    url = _latest_10k_url(keys, ticker)
    if not url:
        return ""
    text = _extract_section(keys, url, item)
    cache_set(cfg, cache_ns, key, {"text": text, "source_url": url})
    return text


def fetch_mda(cfg: Config, keys: ApiKeys, ticker: str, max_chars: int = 4000) -> str:
    """Fetch the latest 10-K's MD&A (Item 7), truncated to max_chars."""
    text = _cached_section(cfg, keys, ticker, "7", "sec_mda")
    return text[:max_chars] if text else ""


def fetch_risk_factors(cfg: Config, keys: ApiKeys, ticker: str, max_chars: int = 4000) -> str:
    """Fetch the latest 10-K's Risk Factors (Item 1A), truncated to max_chars."""
    text = _cached_section(cfg, keys, ticker, "1A", "sec_risk")
    return text[:max_chars] if text else ""


def fetch_business_description(
    cfg: Config, keys: ApiKeys, ticker: str, max_chars: int = 3000
) -> str:
    """Fetch the latest 10-K's Business section (Item 1), truncated."""
    text = _cached_section(cfg, keys, ticker, "1", "sec_business")
    return text[:max_chars] if text else ""


# --- Health check ---


def test_connection(keys: ApiKeys) -> tuple[bool, str]:
    try:
        url = _latest_10k_url(keys, "AAPL")
        if url:
            return True, f"connected; latest AAPL 10-K: {url[:80]}..."
        return False, "no 10-K found for AAPL (unexpected)"
    except SecApiError as e:
        return False, str(e)
