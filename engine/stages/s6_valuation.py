"""
Stage 6: Valuation (DCF + Reverse DCF + Monte Carlo).

Philosophy: Only compute intrinsic value after Stages 1-5 pass. The worst
mistake is falling in love with cheap price before confirming quality.

Three valuation methods (all must agree or flag disagreement):
1. DCF with 3 scenarios (bear/base/bull)
2. Reverse DCF: what growth does current price imply?
3. Monte Carlo: sensitivity over 1000 random paths

WACC dynamic from FRED 10Y + beta + ERP.
"""
from __future__ import annotations

import random
import time

import numpy as np

from engine.models import StageResult, ValuationOutput, ValuationScenario, Verdict
from engine.providers import financial_datasets as fd
from engine.providers import fred as p_fred
from engine.providers import yfinance_provider as yfp
from shared.config import ApiKeys, Config

from ._helpers import aggregate_verdict, make_metric


STAGE_ID = 6
STAGE_NAME = "估值 (DCF + 反向 DCF + Monte Carlo)"


def _compute_wacc(beta: float | None, risk_free: float, erp: float = 5.5) -> float:
    """
    WACC simplified: just cost of equity (most mature tech cos have minimal net debt).
    Ke = Rf + β × ERP
    """
    b = beta if beta is not None else 1.0
    return risk_free + b * erp


def _dcf_value_per_share(
    fcf_latest: float, growth_rate: float, terminal_growth: float,
    wacc: float, years: int, shares_outstanding: float,
) -> float:
    """Project FCF years ahead, discount, add terminal value."""
    if shares_outstanding <= 0 or wacc <= terminal_growth:
        return 0.0

    pv = 0.0
    fcf = fcf_latest
    for y in range(1, years + 1):
        fcf *= (1 + growth_rate / 100)
        pv += fcf / (1 + wacc / 100) ** y

    terminal = fcf * (1 + terminal_growth / 100) / (wacc / 100 - terminal_growth / 100)
    pv += terminal / (1 + wacc / 100) ** years

    return pv / shares_outstanding


_REVERSE_DCF_LO = -20.0
_REVERSE_DCF_HI = 100.0
_REVERSE_DCF_BOUNDARY_EPS = 0.5   # within 0.5% of a bound = didn't converge


def _reverse_dcf_implied_growth(
    current_price: float, fcf_per_share_latest: float,
    wacc: float, terminal_growth: float, years: int = 10,
) -> float | None:
    """
    Binary search for the growth rate that makes DCF ≈ current price.

    Returns None if the answer lies outside the search bracket
    [_REVERSE_DCF_LO, _REVERSE_DCF_HI] — either the stock is so cheap it
    implies growth < -20% (catastrophic expectations) or so hot it implies
    growth > 100% (meme/pre-revenue). A clamped-to-boundary number is worse
    than None because it looks like a real answer.
    """
    if fcf_per_share_latest <= 0 or current_price <= 0:
        return None

    lo, hi = _REVERSE_DCF_LO, _REVERSE_DCF_HI
    for _ in range(50):
        mid = (lo + hi) / 2
        pv = 0.0
        fcf = fcf_per_share_latest
        for y in range(1, years + 1):
            fcf *= (1 + mid / 100)
            pv += fcf / (1 + wacc / 100) ** y
        if wacc / 100 > terminal_growth / 100:
            terminal = fcf * (1 + terminal_growth / 100) / (wacc / 100 - terminal_growth / 100)
            pv += terminal / (1 + wacc / 100) ** years
        if pv > current_price:
            hi = mid
        else:
            lo = mid

    answer = (lo + hi) / 2
    # Converged at a bracket bound → answer is unreliable
    if (answer - _REVERSE_DCF_LO) < _REVERSE_DCF_BOUNDARY_EPS:
        return None
    if (_REVERSE_DCF_HI - answer) < _REVERSE_DCF_BOUNDARY_EPS:
        return None
    return answer


def _monte_carlo(
    fcf_latest: float, shares_outstanding: float, base_wacc: float, years: int = 10,
    trials: int = 500,
) -> tuple[float, float, float]:
    """Return (p5, p50, p95) intrinsic values per share."""
    values = []
    rng = random.Random(42)
    for _ in range(trials):
        growth = rng.gauss(10, 5)            # mean 10%, std 5%
        growth = max(-5, min(35, growth))
        tg = rng.gauss(2.5, 0.5)
        tg = max(0, min(4, tg))
        wacc = max(base_wacc + rng.gauss(0, 1), tg + 0.5)

        v = _dcf_value_per_share(fcf_latest, growth, tg, wacc, years, shares_outstanding)
        values.append(v)

    values.sort()
    p5 = values[int(trials * 0.05)]
    p50 = values[int(trials * 0.50)]
    p95 = values[int(trials * 0.95)]
    return p5, p50, p95


def run(
    cfg: Config, keys: ApiKeys, ticker: str, tech_mode: bool = False,
) -> StageResult:
    t0 = time.time()

    try:
        income = fd.fetch_income_statements(cfg, keys, ticker, period="annual", limit=1)
        cashflow = fd.fetch_cash_flow_statements(cfg, keys, ticker, period="annual", limit=1)
    except fd.FinancialDatasetsError as e:
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=[f"Data unavailable: {e}"],
            elapsed_seconds=time.time() - t0,
        )

    multiples = yfp.fetch_multiples(ticker)
    current_price = yfp.fetch_current_price(ticker)

    metrics = []
    findings = []

    if not (cashflow.periods and income.periods and multiples.shares_outstanding):
        return StageResult(
            stage_id=STAGE_ID, stage_name=STAGE_NAME, verdict=Verdict.SKIP,
            findings=["Missing required data for DCF"],
            elapsed_seconds=time.time() - t0,
        )

    cf0 = cashflow.periods[0]
    fcf_latest = (
        cf0.get("free_cash_flow")
        or ((cf0.get("net_cash_flow_from_operations") or 0) - abs(cf0.get("capital_expenditure") or 0))
    )
    if tech_mode:
        sbc = cf0.get("share_based_compensation") or 0
        fcf_latest -= sbc

    shares = multiples.shares_outstanding or 0
    fcf_per_share = fcf_latest / shares if shares > 0 else 0

    # --- WACC ---
    risk_free = p_fred.fetch_risk_free_rate(cfg, keys)
    beta = multiples.beta or 1.0
    wacc = _compute_wacc(beta, risk_free, erp=5.5)

    findings.append(
        f"**WACC 组件**: Rf {risk_free:.2f}% + β {beta:.2f} × ERP 5.5% = **{wacc:.2f}%**"
    )

    # --- 3 scenarios ---
    scenarios = [
        ("bear", 3.0, 2.0, wacc + 1.0),
        ("base", 8.0, 2.5, wacc),
        ("bull", 15.0, 3.0, max(wacc - 0.5, 2.6)),
    ]
    scenario_outputs = []
    for label, g, tg, w in scenarios:
        iv = _dcf_value_per_share(fcf_latest, g, tg, w, 10, shares)
        scenario_outputs.append(ValuationScenario(
            label=label, fcf_growth_rate=g, terminal_growth=tg, wacc=w,
            intrinsic_value_per_share=iv,
        ))
        findings.append(
            f"  {label.upper()}: FCF 年增 {g}%, 终值增 {tg}%, WACC {w:.2f}% "
            f"→ IV ${iv:.2f}"
        )

    base_iv = scenario_outputs[1].intrinsic_value_per_share

    # --- Reverse DCF ---
    implied_growth = _reverse_dcf_implied_growth(
        current_price or 0, fcf_per_share, wacc, 2.5, years=10,
    )
    if implied_growth is not None:
        findings.append(
            f"**反向 DCF**: 当前价 ${current_price:.2f} 隐含未来 10 年 FCF 年增 **{implied_growth:.1f}%**"
        )
        metrics.append(make_metric(
            "隐含增长率 (反向 DCF)", round(implied_growth, 1),
            "合理区间 5-15%", 5 <= implied_growth <= 15, unit="%",
            note="远低于历史 = 安全边际；远高于历史 = 贵",
        ))

    # --- Monte Carlo ---
    p5, p50, p95 = _monte_carlo(fcf_latest, shares, wacc, years=10, trials=500)
    findings.append(
        f"**Monte Carlo** (500 次模拟): P5 ${p5:.2f} / P50 ${p50:.2f} / P95 ${p95:.2f}"
    )

    # --- Current price vs base IV ---
    if current_price and base_iv > 0:
        discount_pct = (base_iv - current_price) / base_iv * 100
        metrics.append(make_metric(
            "当前价 vs 基准 IV", f"${current_price:.2f} / ${base_iv:.2f}",
            "IV 至少高出 20% (buffer)", discount_pct >= 20,
            note=f"折让 {discount_pct:.1f}%" if discount_pct >= 0 else f"溢价 {abs(discount_pct):.1f}%",
        ))

    # --- Valuation multiples check (historical percentile) ---
    if multiples.trailing_pe:
        metrics.append(make_metric(
            "Trailing P/E", round(multiples.trailing_pe, 1),
            "行业依赖",
            None,  # not binary
        ))
    if multiples.forward_pe:
        metrics.append(make_metric(
            "Forward P/E", round(multiples.forward_pe, 1),
            "< 25 (非高成长) | < 35 (高成长)",
            multiples.forward_pe < (35 if tech_mode else 25),
        ))

    valuation = ValuationOutput(
        current_price=current_price,
        dcf_scenarios=scenario_outputs,
        reverse_dcf_implied_growth=implied_growth,
        monte_carlo_p5=p5,
        monte_carlo_p50=p50,
        monte_carlo_p95=p95,
    )

    verdict = aggregate_verdict(metrics)

    return StageResult(
        stage_id=STAGE_ID,
        stage_name=STAGE_NAME,
        verdict=verdict,
        metrics=metrics,
        findings=findings,
        raw_data={
            "wacc": wacc,
            "risk_free_rate": risk_free,
            "beta": beta,
            "fcf_latest": fcf_latest,
            "fcf_per_share": fcf_per_share,
            "shares_outstanding": shares,
            "valuation": valuation.model_dump(),
        },
        elapsed_seconds=time.time() - t0,
    )
