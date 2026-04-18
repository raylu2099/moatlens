"""
yfinance — free provider for historical prices, valuation multiples, and
info fields. Always available (no API key needed).

Used for:
- Historical price series (for DCF sensitivity, historical multiple percentiles)
- .info fields (market cap, trailing PE, forward PE, beta)
- Historical multiple calculations
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import yfinance as yf


@dataclass
class PriceHistory:
    ticker: str
    close_prices: list[float]  # newest last
    dates: list[str]           # YYYY-MM-DD


@dataclass
class MultipleSnapshot:
    ticker: str
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_sales_ttm: float | None = None
    price_to_book: float | None = None
    peg_ratio: float | None = None
    dividend_yield: float | None = None
    market_cap: float | None = None       # in USD
    enterprise_value: float | None = None
    ev_to_ebitda: float | None = None
    beta: float | None = None
    shares_outstanding: float | None = None
    err: str = ""


def fetch_history(ticker: str, period: str = "5y") -> PriceHistory | None:
    try:
        hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        if hist is None or hist.empty:
            return None
        closes = [float(x) for x in hist["Close"].tolist()]
        dates = [d.strftime("%Y-%m-%d") for d in hist.index]
        return PriceHistory(ticker=ticker, close_prices=closes, dates=dates)
    except Exception as e:
        print(f"[yfinance] history {ticker}: {e}", file=sys.stderr)
        return None


def fetch_multiples(ticker: str) -> MultipleSnapshot:
    snap = MultipleSnapshot(ticker=ticker)
    try:
        info = yf.Ticker(ticker).info or {}
        snap.trailing_pe = info.get("trailingPE")
        snap.forward_pe = info.get("forwardPE")
        snap.price_to_sales_ttm = info.get("priceToSalesTrailing12Months")
        snap.price_to_book = info.get("priceToBook")
        snap.peg_ratio = info.get("pegRatio")
        snap.dividend_yield = info.get("dividendYield")
        snap.market_cap = info.get("marketCap")
        snap.enterprise_value = info.get("enterpriseValue")
        snap.ev_to_ebitda = info.get("enterpriseToEbitda")
        snap.beta = info.get("beta")
        snap.shares_outstanding = info.get("sharesOutstanding")
    except Exception as e:
        snap.err = str(e)[:100]
    return snap


def fetch_current_price(ticker: str) -> float | None:
    try:
        fi = yf.Ticker(ticker).fast_info
        return float(getattr(fi, "last_price", None) or fi.get("lastPrice"))
    except Exception:
        return None


def fetch_company_info(ticker: str) -> dict:
    """Return metadata useful for context (sector, industry, long biz summary)."""
    try:
        info = yf.Ticker(ticker).info or {}
        return {
            "long_name": info.get("longName") or info.get("shortName") or ticker,
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "country": info.get("country", ""),
            "website": info.get("website", ""),
            "business_summary": info.get("longBusinessSummary", ""),
            "full_time_employees": info.get("fullTimeEmployees"),
        }
    except Exception:
        return {"long_name": ticker}


def test_connection() -> tuple[bool, str]:
    try:
        p = fetch_current_price("AAPL")
        return (p is not None and p > 0), f"AAPL = ${p}" if p else "no price returned"
    except Exception as e:
        return False, str(e)
