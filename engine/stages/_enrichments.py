"""
Stage enrichment helpers (v0.6).

Purpose: add *findings-only* enrichment from optional v0.6 providers
(sec_api, finnhub, marketaux, fda) without touching verdict logic.

Design rules:
- Every function catches its own exceptions → returns None on any failure
- Returns pre-formatted markdown string OR None
- Never raises to the calling stage
- If the relevant API key is missing, returns None silently
- Sector-gated helpers (FDA) take sector as explicit param, caller decides

Why findings-only: the existing 144 tests assert verdict behavior based on
metrics rules. New providers are *color*, not signal — they make the report
richer to read but don't change PASS/FAIL outcomes. This preserves invariants.
"""

from __future__ import annotations

from shared.config import ApiKeys, Config


def sec_mda_excerpt(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    max_chars: int = 600,
) -> str | None:
    """One-paragraph finding from the latest 10-K MD&A (Item 7)."""
    if not keys.sec_api_io:
        return None
    try:
        from engine.providers import sec_api

        text = sec_api.fetch_mda(cfg, keys, ticker, max_chars=max_chars * 2)
    except Exception:
        return None
    if not text:
        return None
    # Trim to first paragraph or max_chars
    snippet = text.split("\n\n")[0][:max_chars].strip()
    if not snippet:
        return None
    return f"**📜 SEC MD&A（最近 10-K Item 7 摘录）**: {snippet}..."


def sec_risk_factors_excerpt(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    max_chars: int = 800,
) -> str | None:
    """Raw Risk Factors text (for injection into Claude context or findings)."""
    if not keys.sec_api_io:
        return None
    try:
        from engine.providers import sec_api

        text = sec_api.fetch_risk_factors(cfg, keys, ticker, max_chars=max_chars)
    except Exception:
        return None
    return text or None


def finnhub_insider_summary(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
) -> tuple[str | None, dict | None]:
    """Returns (finding_line, raw_dict). Raw saved in raw_data for snapshots."""
    if not keys.finnhub:
        return None, None
    try:
        from engine.providers import finnhub

        data = finnhub.fetch_insider_transactions(cfg, keys, ticker, days=180)
    except Exception:
        return None, None
    if data.get("tx_count", 0) == 0:
        return None, data
    direction = (
        "净买入" if data["net_shares"] > 0 else ("净卖出" if data["net_shares"] < 0 else "持平")
    )
    line = (
        f"**📊 Finnhub 内部人交易（180 天）**: {data['tx_count']} 笔, "
        f"{direction} {abs(data['net_shares']):,} 股 "
        f"(${abs(data['net_dollars'])/1e6:.1f}M)"
    )
    return line, data


def finnhub_consensus_summary(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
) -> tuple[str | None, dict | None]:
    """Returns (finding_line, raw_dict)."""
    if not keys.finnhub:
        return None, None
    try:
        from engine.providers import finnhub

        rows = finnhub.fetch_recommendation_trends(cfg, keys, ticker)
        summary = finnhub.summarize_consensus(rows)
    except Exception:
        return None, None
    if summary.get("label") == "n/a":
        return None, summary
    label_cn = {
        "overwhelmingly_bullish": "压倒性看多",
        "bullish": "偏多",
        "skeptical": "偏谨慎",
        "mixed": "分歧",
    }.get(summary["label"], summary["label"])
    line = (
        f"**🎯 分析师共识（{summary.get('period', '')}）**: {label_cn} "
        f"({summary['total_analysts']} 人, 看多 {summary['bullish_pct']}%, 看空 {summary['bearish_pct']}%)"
    )
    return line, summary


def marketaux_sentiment_summary(
    cfg: Config,
    keys: ApiKeys,
    ticker: str,
    days: int = 30,
) -> tuple[str | None, dict | None]:
    """Returns (finding_line, raw_dict)."""
    if not keys.marketaux:
        return None, None
    try:
        from engine.providers import marketaux

        data = marketaux.fetch_news_sentiment(cfg, keys, ticker, days=days)
        label = marketaux.sentiment_label(data["avg_sentiment"], data["article_count"])
    except Exception:
        return None, None
    if label == "n/a":
        return None, data
    label_cn = {
        "strongly_positive": "强烈正面",
        "mildly_positive": "偏正面",
        "strongly_negative": "强烈负面",
        "mildly_negative": "偏负面",
        "neutral": "中性",
    }.get(label, label)
    line = (
        f"**📰 新闻情绪（{days} 天，MarketAux）**: {label_cn} "
        f"(avg={data['avg_sentiment']:+.2f}, {data['article_count']} 篇, "
        f"正面 {data['positive_pct']}%, 负面 {data['negative_pct']}%)"
    )
    return line, data


def fda_pipeline_summary(
    cfg: Config,
    keys: ApiKeys,
    company_name: str,
    sector: str = "",
) -> tuple[str | None, dict | None]:
    """Pharma-only. Callers pass sector string; we gate on Healthcare."""
    if not sector or "health" not in sector.lower():
        return None, None
    if not company_name:
        return None, None
    try:
        from engine.providers import fda

        data = fda.pipeline_summary(cfg, keys, company_name)
    except Exception:
        return None, None
    strength_cn = {
        "deep": "深厚",
        "moderate": "中等",
        "thin": "单薄",
        "dry": "枯竭",
    }.get(data.get("pipeline_strength", ""), data.get("pipeline_strength", ""))
    line = (
        f"**💊 FDA Pipeline（{data.get('company', company_name)}）**: "
        f"{strength_cn}  —  "
        f"活跃 Phase 3: {data['active_phase_3']}, Phase 2: {data['active_phase_2']}, "
        f"近 5 年批准: {data['approvals_last_5y']}"
    )
    if data.get("pipeline_strength") == "dry":
        line += "\n  ⚠️ **红旗**: 无 Phase 3 在研，专利悬崖到期后增长来源成疑"
    return line, data
