"""
Stage 1: Circle of Competence + Trash Bin test.

Philosophy: In 3 minutes, decide if this company is even worth deeper analysis.
Fail-fast. If ROIC < 15% for 10 years, Buffett says "even a second look is wasted".

Rules:
- ROIC avg (5Y) > 15%
- Gross margin TTM > 40%
- Interest coverage > 5x
- Altman Z-score > 2.5
- Revenue growing (5Y CAGR > 0%)

Tech stock adjustment: gross margin threshold varies by industry
(software > 70%, hardware > 25%) — applied in tech mode.
"""
from __future__ import annotations

import time
from typing import Any

from engine.models import StageResult, Verdict
from engine.providers import financial_datasets as fd
from engine.providers import yfinance_provider as yfp
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, cagr, make_metric


STAGE_ID = 1
STAGE_NAME = "能力圈 & 垃圾桶测试"


def _compute_roic(income: list[dict], balance: list[dict]) -> list[float]:
    """Return ROIC % per year, newest first."""
    results = []
    for i_stmt, b_stmt in zip(income, balance):
        try:
            ebit = i_stmt.get("operating_income") or i_stmt.get("ebit")
            tax = i_stmt.get("income_tax_expense") or 0
            pretax = i_stmt.get("ebit") or ebit
            tax_rate = (tax / pretax) if pretax and pretax > 0 else 0.21
            nopat = ebit * (1 - tax_rate) if ebit else None

            invested_capital = (
                (b_stmt.get("total_debt") or 0)
                + (b_stmt.get("shareholders_equity") or 0)
                - (b_stmt.get("cash_and_equivalents") or 0)
            )
            if nopat and invested_capital > 0:
                results.append(nopat / invested_capital * 100)
        except Exception:
            continue
    return results


def _altman_z(income: dict, balance: dict, market_cap: float | None) -> float | None:
    """Altman Z-score for non-financial public companies."""
    try:
        total_assets = balance.get("total_assets")
        total_liab = balance.get("total_liabilities")
        retained_earnings = balance.get("retained_earnings") or 0
        ebit = income.get("operating_income") or income.get("ebit") or 0
        revenue = income.get("revenue") or 0
        current_assets = balance.get("current_assets") or 0
        current_liab = balance.get("current_liabilities") or 0
        working_capital = current_assets - current_liab

        if not total_assets or total_assets == 0 or not market_cap:
            return None

        a = working_capital / total_assets
        b = retained_earnings / total_assets
        c = ebit / total_assets
        d = market_cap / total_liab if total_liab else 0
        e = revenue / total_assets

        z = 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e
        return z
    except Exception:
        return None


def run(cfg: Config, keys: ApiKeys, ticker: str, tech_mode: bool = False) -> StageResult:
    t0 = time.time()

    # Fetch data
    try:
        income = fd.fetch_income_statements(cfg, keys, ticker, period="annual", limit=6)
        balance = fd.fetch_balance_sheets(cfg, keys, ticker, period="annual", limit=6)
    except fd.FinancialDatasetsError as e:
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=[f"Data unavailable: {e}"],
            elapsed_seconds=time.time() - t0,
        )

    multiples = yfp.fetch_multiples(ticker)
    info = yfp.fetch_company_info(ticker)

    metrics = []
    findings = []

    # --- ROIC 5-year average ---
    roics = _compute_roic(income.periods, balance.periods)
    if roics:
        avg_roic = sum(roics[:5]) / min(len(roics), 5)
        pass_roic = avg_roic > 15
        metrics.append(make_metric(
            "ROIC (5Y avg)", round(avg_roic, 1),
            "> 15%", pass_roic, unit="%",
            note=f"Individual years: {[round(r, 1) for r in roics[:5]]}",
        ))
    else:
        metrics.append(make_metric("ROIC (5Y avg)", None, "> 15%", False, note="计算失败"))

    # --- Gross margin ---
    gm_threshold = 70 if tech_mode else 40
    if income.periods:
        latest = income.periods[0]
        revenue = latest.get("revenue") or 0
        cogs = latest.get("cost_of_revenue") or 0
        if revenue > 0:
            gm = (revenue - cogs) / revenue * 100
            metrics.append(make_metric(
                "Gross Margin (TTM)", round(gm, 1),
                f"> {gm_threshold}%", gm > gm_threshold, unit="%",
                note="定价权标志" if gm > gm_threshold else "可能处于产业链苦力位",
            ))

    # --- Interest coverage ---
    if income.periods:
        latest = income.periods[0]
        ebit = latest.get("operating_income") or latest.get("ebit") or 0
        interest = latest.get("interest_expense") or 0
        if interest > 0:
            coverage = ebit / interest
            metrics.append(make_metric(
                "Interest Coverage", round(coverage, 1),
                "> 5x", coverage > 5, unit="x",
            ))
        else:
            metrics.append(make_metric(
                "Interest Coverage", "∞",
                "> 5x", True,
                note="零利息支出 (无长期债务)",
            ))

    # --- Revenue growth (5Y CAGR) ---
    if len(income.periods) >= 5:
        latest_rev = income.periods[0].get("revenue")
        old_rev = income.periods[4].get("revenue")
        if latest_rev and old_rev:
            rev_cagr = cagr(latest_rev, old_rev, 4)
            if rev_cagr is not None:
                metrics.append(make_metric(
                    "Revenue CAGR (5Y)", round(rev_cagr, 1),
                    "> 0%", rev_cagr > 0, unit="%",
                ))

    # --- Altman Z-score ---
    if income.periods and balance.periods:
        z = _altman_z(income.periods[0], balance.periods[0], multiples.market_cap)
        if z is not None:
            metrics.append(make_metric(
                "Altman Z-score", round(z, 1),
                "> 2.5", z > 2.5, unit="",
                note="破产风险预警" if z <= 2.5 else "财务稳健",
            ))

    # --- Qualitative findings ---
    company_name = info.get("long_name", ticker)
    biz_summary = info.get("business_summary", "")
    if biz_summary:
        findings.append(f"**{company_name}** ({info.get('sector', '?')} / {info.get('industry', '?')})")
        findings.append(f"Business: {biz_summary[:300]}...")

    findings.append(
        "⚠️ 能力圈自检（系统无法替你判断）：你能用 2-3 句话讲清楚这家公司怎么赚钱吗？"
    )

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "company_info": info,
            "latest_income_period": income.periods[0] if income.periods else {},
            "latest_balance_period": balance.periods[0] if balance.periods else {},
            "roic_series": roics,
            "multiples": {
                "market_cap": multiples.market_cap,
                "trailing_pe": multiples.trailing_pe,
                "forward_pe": multiples.forward_pe,
            },
        },
        elapsed_seconds=time.time() - t0,
    )
