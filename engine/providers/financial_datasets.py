"""
Financial Datasets API — fundamentals provider.
https://financialdatasets.ai/

Endpoints used:
- /financials/income-statements?period=annual|quarterly
- /financials/balance-sheets
- /financials/cash-flow-statements
- /analyst-estimates
- /earnings (BEAT/MISS summary)
- /insider-trades
- /prices/snapshot
- /company/facts
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import requests

from engine.cache import cache_get, cache_set
from shared.config import ApiKeys, Config


API_BASE = "https://api.financialdatasets.ai"


@dataclass
class FundamentalSeries:
    """Multi-year financial statement rollup."""
    ticker: str
    periods: list[dict[str, Any]]   # newest first, each dict = one period
    period_type: str                # "annual" or "quarterly"


class FinancialDatasetsError(RuntimeError):
    pass


def _api_get(keys: ApiKeys, path: str, params: dict) -> dict:
    if not keys.financial_datasets:
        raise FinancialDatasetsError("FINANCIAL_DATASETS_API_KEY missing")
    # Rate-limit guard — protects subscription quota from runaway loops
    try:
        from shared.ratelimit import require_token
        require_token("financial_datasets")
    except ImportError:
        pass
    except Exception as e:
        raise FinancialDatasetsError(f"rate-limit: {e}")
    url = f"{API_BASE}/{path}"
    try:
        r = requests.get(
            url,
            params=params,
            headers={"X-API-Key": keys.financial_datasets},
            timeout=20,
        )
    except Exception as e:
        raise FinancialDatasetsError(f"network error on {path}: {e}")
    if r.status_code == 401:
        raise FinancialDatasetsError("Invalid FINANCIAL_DATASETS_API_KEY (401)")
    if r.status_code == 404:
        raise FinancialDatasetsError(f"Endpoint not found: {path}")
    if r.status_code != 200:
        raise FinancialDatasetsError(f"HTTP {r.status_code} for {path}: {r.text[:200]}")
    return r.json()


def _cached_api_get(
    cfg: Config, keys: ApiKeys, path: str, params: dict, cache_ns: str,
) -> dict:
    """Cached wrapper — public fundamentals shareable across users."""
    cache_key = f"{path}?{'&'.join(f'{k}={v}' for k, v in sorted(params.items()))}"
    cached = cache_get(cfg, cache_ns, cache_key, cfg.cache_fundamentals_ttl)
    if cached is not None:
        return cached
    data = _api_get(keys, path, params)
    cache_set(cfg, cache_ns, cache_key, data)
    return data


def fetch_income_statements(
    cfg: Config, keys: ApiKeys, ticker: str, period: str = "annual", limit: int = 10,
) -> FundamentalSeries:
    data = _cached_api_get(
        cfg, keys, "financials/income-statements",
        {"ticker": ticker, "period": period, "limit": limit},
        "fd_income",
    )
    return FundamentalSeries(
        ticker=ticker,
        periods=data.get("income_statements", []),
        period_type=period,
    )


def fetch_balance_sheets(
    cfg: Config, keys: ApiKeys, ticker: str, period: str = "annual", limit: int = 10,
) -> FundamentalSeries:
    data = _cached_api_get(
        cfg, keys, "financials/balance-sheets",
        {"ticker": ticker, "period": period, "limit": limit},
        "fd_balance",
    )
    return FundamentalSeries(
        ticker=ticker,
        periods=data.get("balance_sheets", []),
        period_type=period,
    )


def fetch_cash_flow_statements(
    cfg: Config, keys: ApiKeys, ticker: str, period: str = "annual", limit: int = 10,
) -> FundamentalSeries:
    data = _cached_api_get(
        cfg, keys, "financials/cash-flow-statements",
        {"ticker": ticker, "period": period, "limit": limit},
        "fd_cashflow",
    )
    return FundamentalSeries(
        ticker=ticker,
        periods=data.get("cash_flow_statements", []),
        period_type=period,
    )


def fetch_earnings_summary(cfg: Config, keys: ApiKeys, ticker: str) -> dict:
    """Latest BEAT/MISS + actual vs estimated EPS."""
    data = _cached_api_get(
        cfg, keys, "earnings", {"ticker": ticker}, "fd_earnings",
    )
    return data.get("earnings", {})


def fetch_analyst_estimates(
    cfg: Config, keys: ApiKeys, ticker: str, limit: int = 3,
) -> list[dict]:
    """Forward EPS + revenue estimates."""
    data = _cached_api_get(
        cfg, keys, "analyst-estimates",
        {"ticker": ticker, "limit": limit},
        "fd_estimates",
    )
    return data.get("analyst_estimates", [])


def fetch_insider_trades(
    cfg: Config, keys: ApiKeys, ticker: str, limit: int = 20,
) -> list[dict]:
    """Recent insider buys/sells."""
    data = _cached_api_get(
        cfg, keys, "insider-trades",
        {"ticker": ticker, "limit": limit},
        "fd_insider",
    )
    return data.get("insider_trades", [])


def fetch_price_snapshot(keys: ApiKeys, ticker: str) -> dict:
    """Real-time price snapshot — not cached (prices change fast)."""
    data = _api_get(keys, "prices/snapshot", {"ticker": ticker})
    return data.get("snapshot", {})


def fetch_company_facts(cfg: Config, keys: ApiKeys, ticker: str) -> dict:
    """Company metadata (name, industry, market cap, etc.)."""
    try:
        data = _cached_api_get(
            cfg, keys, "company/facts", {"ticker": ticker}, "fd_facts",
        )
        return data.get("company_facts", {})
    except FinancialDatasetsError:
        return {}


# --- Health check ---

def test_connection(keys: ApiKeys) -> tuple[bool, str]:
    """Ping API with a known ticker. Returns (ok, message)."""
    try:
        data = _api_get(keys, "prices/snapshot", {"ticker": "AAPL"})
        price = data.get("snapshot", {}).get("price")
        if price:
            return True, f"connected; AAPL price ${price}"
        return False, "unexpected response shape"
    except FinancialDatasetsError as e:
        return False, str(e)
